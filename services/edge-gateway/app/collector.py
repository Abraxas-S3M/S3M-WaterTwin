"""Collection loop: read -> validate -> convert -> stamp -> buffer -> forward.

Ties the pieces together for one polling cycle:

1. resolve the active OT source (shared read-only resolver; graceful fallback to
   synthetic when a configured real source is down);
2. read the latest canonical readings (strictly read-only);
3. convert units, assign a data-quality flag, and apply a monotonic gateway
   timestamp;
4. append everything to the encrypted store-and-forward buffer; then
5. drain the buffer and push it OUTBOUND to the API, acking only what the API
   confirms (so an outage leaves rows buffered for replay).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from ot_ingestion.sources import resolve_source

from .conversions import to_canonical
from .forwarder import ForwardResult
from .health import SourceHealth
from .quality import QualityMonitor
from .timesync import MonotonicClock

logger = logging.getLogger("edge_gateway.collector")


class Collector:
    """Orchestrates one (or a continuous loop of) collect + forward cycles."""

    def __init__(
        self,
        config: Any,
        buffer: Any,
        forwarder: Any,
        *,
        quality: Optional[QualityMonitor] = None,
        clock: Optional[MonotonicClock] = None,
        health: Optional[SourceHealth] = None,
        resolver: Callable[[Any], Any] = resolve_source,
    ) -> None:
        self._config = config
        self._buffer = buffer
        self._forwarder = forwarder
        self._resolver = resolver
        self._quality = quality or QualityMonitor(
            staleness_limit_s=getattr(config, "STALENESS_LIMIT_S", 60.0),
            frozen_limit=getattr(config, "FROZEN_LIMIT", 10),
            deadband=getattr(config, "DEADBAND", 0.0),
        )
        self._clock = clock or MonotonicClock()
        self._health = health or SourceHealth(gateway_id=getattr(config, "GATEWAY_ID", "edge-gateway"))
        self._resolution: Optional[Any] = None

    @property
    def health(self) -> SourceHealth:
        return self._health

    # -- source resolution ----------------------------------------------------

    def _resolve(self) -> Any:
        self._resolution = self._resolver(self._config)
        self._health.update_resolution(self._resolution)
        logger.info(
            "active OT source: %s (requested=%s, fallback=%s)",
            self._resolution.active,
            self._resolution.requested,
            self._resolution.fallback,
        )
        return self._resolution

    def _ensure_resolution(self) -> Any:
        if self._resolution is None:
            return self._resolve()
        return self._resolution

    # -- one cycle ------------------------------------------------------------

    def collect_once(self) -> int:
        """Read, quality-check, stamp, and buffer one batch. Returns count buffered.

        If the active real source read fails, records the failure and re-resolves
        (which gracefully falls back to synthetic) so collection continues.
        """
        resolution = self._ensure_resolution()
        readings = self._read(resolution)
        if readings is None:
            # First read failed: fall back (re-resolve -> synthetic) and retry.
            resolution = self._resolve()
            readings = self._read(resolution)
        if readings is None:
            return 0

        records: list[dict[str, Any]] = []
        for reading in readings:
            value, unit = to_canonical(reading.value, reading.unit)
            result = self._quality.evaluate(reading.asset_id, reading.metric, value, reading.timestamp)
            stamped_ts, skew = self._clock.stamp(reading.timestamp)
            self._health.set_skew(skew)
            provenance = getattr(reading.provenance, "value", str(reading.provenance))
            records.append(
                {
                    "asset_id": reading.asset_id,
                    "metric": reading.metric,
                    "value": value,
                    "unit": unit,
                    "timestamp": stamped_ts,
                    "provenance": provenance,
                    "quality": result.flag,
                }
            )

        self._buffer.append_many(records)
        self._health.set_buffer_depth(self._buffer.count())
        return len(records)

    def _read(self, resolution: Any) -> Optional[list]:
        try:
            readings = resolution.source.read_latest()
            self._health.record_read_success(len(readings))
            return readings
        except Exception as exc:
            self._health.record_read_failure(f"{type(exc).__name__}: {exc}")
            logger.warning("source read failed (%s): %s", resolution.active, exc)
            return None

    def flush_once(self) -> ForwardResult:
        """Drain the buffer FIFO and push it outbound; ack only confirmed rows."""
        pending = self._buffer.pending(getattr(self._config, "FORWARD_BATCH_SIZE", 500))
        if not pending:
            return ForwardResult(ok=True, accepted=0)
        ids = [row_id for row_id, _ in pending]
        records = [record for _, record in pending]
        result = self._forwarder.send(
            records,
            source=self._health.active_source,
            fallback=self._health.fallback,
            source_health=self._health.snapshot(),
        )
        if result.ok:
            self._buffer.ack(ids)
            self._health.record_forward_success(len(ids))
        else:
            self._health.record_forward_failure(result.error or "forward failed")
        self._health.set_buffer_depth(self._buffer.count())
        return result

    def run_once(self) -> ForwardResult:
        """Run a single collect + flush cycle."""
        self.collect_once()
        return self.flush_once()

    def run_forever(self, stop_event: Optional[threading.Event] = None) -> None:
        """Run the collect + flush loop until ``stop_event`` is set."""
        stop_event = stop_event or threading.Event()
        interval = getattr(self._config, "POLL_INTERVAL_S", 5.0)
        heartbeat_path = getattr(self._config, "HEARTBEAT_PATH", None)
        logger.info("edge-gateway collection loop starting (interval=%ss)", interval)
        while not stop_event.is_set():
            try:
                self.run_once()
                self._touch_heartbeat(heartbeat_path)
            except Exception as exc:  # defensive: the loop must never die
                logger.exception("collection cycle error: %s", exc)
            stop_event.wait(interval)
        logger.info("edge-gateway collection loop stopped")

    @staticmethod
    def _touch_heartbeat(path: Optional[str]) -> None:
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        except OSError as exc:  # pragma: no cover - defensive
            logger.warning("could not write heartbeat %s: %s", path, exc)
