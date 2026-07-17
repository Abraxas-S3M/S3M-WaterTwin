"""Outbound-only push client to the watertwin-api ingest endpoint.

The forwarder is the gateway's ONLY network path and it is strictly outbound: it
dials the watertwin-api ingest URL as an HTTP client and never listens for
inbound connections. On any failure it returns ``ok=False`` so the collector
leaves the readings buffered for a later retry (store-and-forward); it never
raises into the collection loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from canonical_water_model import now_iso

logger = logging.getLogger("edge_gateway.forwarder")


@dataclass
class ForwardResult:
    ok: bool
    accepted: int = 0
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
