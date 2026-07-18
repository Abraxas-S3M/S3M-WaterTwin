"""Outbound-only push clients to the watertwin-api ingest endpoint.

The forwarders are the gateway's ONLY network path and they are strictly
outbound: they dial the watertwin-api ingest URL as an HTTP client and never
listen for inbound connections. On any failure they return ``ok=False`` so the
caller leaves the readings buffered/spooled for a later retry (store-and-forward);
they never raise into the collection loop.

Two cooperating mechanisms share this module:

* :class:`HttpForwarder` -- a stateless push client used by the collector loop
  (:mod:`app.collector`) alongside the encrypted buffer; and
* :class:`Gateway` -- a durable, spool-backed store-and-forward engine that runs
  its own producer + forwarder loops (:mod:`app.spool`), replaying every un-acked
  batch after a restart (upstream de-duplicates on the idempotent batch id).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from canonical_water_model import now_iso

from . import config
from .generator import build_readings
from .spool import Spool, SpooledBatch

logger = logging.getLogger("edge_gateway.forwarder")


@dataclass
class ForwardResult:
    """Outcome of a single forward attempt (union of both forwarders)."""

    ok: bool
    accepted: int = 0
    duplicate: bool = False
    status: Optional[int] = None
    error: Optional[str] = None


class HttpForwarder:
    """Pushes canonical readings to the API ingest endpoint (outbound only)."""

    def __init__(
        self,
        *,
        base_url: str,
        ingest_path: str,
        gateway_id: str,
        token: Optional[str] = None,
        timeout: float = 10.0,
        client: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ingest_path = ingest_path if ingest_path.startswith("/") else f"/{ingest_path}"
        self.gateway_id = gateway_id
        self.token = token
        self.timeout = timeout
        self._client = client

    @property
    def url(self) -> str:
        return f"{self.base_url}{self.ingest_path}"

    def _build_client(self) -> Any:
        if self._client is not None:
            return self._client
        import httpx  # lazy: outbound HTTP client only

        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        self._client = httpx.Client(timeout=self.timeout, headers=headers)
        return self._client

    def send(
        self,
        records: list[dict[str, Any]],
        *,
        source: Optional[str] = None,
        fallback: bool = False,
        source_health: Optional[dict[str, Any]] = None,
    ) -> ForwardResult:
        """POST a batch of readings to the API ingest endpoint (outbound)."""
        if not records:
            return ForwardResult(ok=True, accepted=0)
        payload = {
            "gateway_id": self.gateway_id,
            "source": source,
            "fallback": fallback,
            "source_health": source_health,
            "sent_at": now_iso(),
            "readings": records,
        }
        try:
            client = self._build_client()
            response = client.post(self.url, json=payload)
            response.raise_for_status()
            body = response.json() if response.content else {}
            accepted = int(body.get("accepted", len(records)))
            return ForwardResult(ok=True, accepted=accepted)
        except Exception as exc:  # never propagate into the collection loop
            logger.warning("outbound push to %s failed: %s", self.url, exc)
            return ForwardResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    def close(self) -> None:
        client = self._client
        if client is not None and hasattr(client, "close"):
            try:
                client.close()
            except Exception:  # pragma: no cover - defensive
                pass


@dataclass
class Stats:
    """Live counters for /health and /stats (guarded by an internal lock)."""

    produced: int = 0
    forwarded: int = 0
    duplicates: int = 0
    forward_attempts: int = 0
    forward_failures: int = 0
    api_reachable: bool = False
    last_error: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "produced": self.produced,
                "forwarded": self.forwarded,
                "duplicates": self.duplicates,
                "forward_attempts": self.forward_attempts,
                "forward_failures": self.forward_failures,
                "api_reachable": self.api_reachable,
                "last_error": self.last_error,
            }


#: A forward function maps a batch payload to a :class:`ForwardResult`.
ForwardFn = Callable[[dict[str, Any]], ForwardResult]


def http_forward(payload: dict[str, Any]) -> ForwardResult:
    """Default forwarder: POST a batch to the central API ingest endpoint."""
    import httpx

    headers = {}
    if config.INGEST_TOKEN:
        headers["X-Ingest-Token"] = config.INGEST_TOKEN
    url = f"{config.API_URL}{config.INGEST_PATH}"
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=config.FORWARD_TIMEOUT_S)
    except Exception as exc:  # network failure -> retry later
        return ForwardResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    if resp.status_code == 200:
        try:
            duplicate = bool(resp.json().get("duplicate", False))
        except Exception:
            duplicate = False
        return ForwardResult(ok=True, duplicate=duplicate, status=200)
    return ForwardResult(ok=False, status=resp.status_code, error=resp.text[:200])


class Gateway:
    """Owns the spool + producer/forwarder loops and their live stats."""

    def __init__(
        self,
        *,
        spool: Optional[Spool] = None,
        forward_fn: Optional[ForwardFn] = None,
        gateway_id: str = config.GATEWAY_ID,
    ) -> None:
        self.spool = spool or Spool(config.SPOOL_DIR)
        self.forward_fn: ForwardFn = forward_fn or http_forward
        self.gateway_id = gateway_id
        self.stats = Stats()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._tick = 0

    # -- single-step primitives (also drive the background loops) -------------

    def produce_once(self) -> SpooledBatch:
        """Synthesize one batch and append it to the durable spool."""
        self._tick += 1
        seq = self.spool.next_seq()
        batch_id = f"{self.gateway_id}-{seq:012d}"
        payload = {
            "batch_id": batch_id,
            "readings": build_readings(self._tick),
            "source": self.gateway_id,
        }
        path = self.spool.append(seq, payload)
        with self.stats._lock:
            self.stats.produced += 1
        return SpooledBatch(seq=seq, path=path, payload=payload)

    def forward_once(self) -> Optional[ForwardResult]:
        """Attempt to forward the oldest spooled batch. ``None`` if spool empty."""
        batch = self.spool.peek()
        if batch is None:
            return None
        result = self.forward_fn(batch.payload)
        with self.stats._lock:
            self.stats.forward_attempts += 1
            if result.ok:
                self.spool.ack(batch)
                self.stats.forwarded += 1
                if result.duplicate:
                    self.stats.duplicates += 1
                self.stats.api_reachable = True
                self.stats.last_error = None
            else:
                self.stats.forward_failures += 1
                self.stats.api_reachable = False
                self.stats.last_error = result.error
        return result

    def drain(self) -> int:
        """Forward every spooled batch until one fails or the spool empties.

        Returns the number of batches successfully forwarded. Used by tests and
        by the chaos/DR drills to deterministically flush the spool.
        """
        count = 0
        while not self._stop.is_set():
            result = self.forward_once()
            if result is None or not result.ok:
                break
            count += 1
        return count

    # -- background loops -----------------------------------------------------

    def _producer_loop(self) -> None:
        while not self._stop.is_set():
            if config.MAX_BATCHES and self.stats.snapshot()["produced"] >= config.MAX_BATCHES:
                break
            try:
                self.produce_once()
            except Exception as exc:  # never let the edge feed crash the loop
                logger.warning("produce failed: %s", exc)
            self._stop.wait(config.BATCH_INTERVAL_S)

    def _forwarder_loop(self) -> None:
        backoff = config.FORWARD_INTERVAL_S
        while not self._stop.is_set():
            result = self.forward_once()
            if result is None:
                backoff = config.FORWARD_INTERVAL_S
                self._stop.wait(config.FORWARD_INTERVAL_S)
            elif result.ok:
                backoff = config.FORWARD_INTERVAL_S
            else:
                self._stop.wait(backoff)
                backoff = min(backoff * 2, config.FORWARD_MAX_BACKOFF_S)

    def start(self) -> None:
        """Start the forwarder (always) and producer (when enabled) threads."""
        self._stop.clear()
        forwarder = threading.Thread(target=self._forwarder_loop, name="edge-forwarder", daemon=True)
        forwarder.start()
        self._threads = [forwarder]
        if config.PRODUCE_ENABLED:
            producer = threading.Thread(target=self._producer_loop, name="edge-producer", daemon=True)
            producer.start()
            self._threads.append(producer)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads = []

    def health(self) -> dict[str, Any]:
        snap = self.stats.snapshot()
        return {
            "service": config.SERVICE_NAME,
            "version": config.SERVICE_VERSION,
            "status": "healthy",
            "gateway_id": self.gateway_id,
            "api_url": f"{config.API_URL}{config.INGEST_PATH}",
            "spool_dir": self.spool.dir,
            "spool_depth": self.spool.depth(),
            # The gateway only reads/forwards telemetry -- never a control write.
            "control_write_enabled": False,
            **snap,
        }
