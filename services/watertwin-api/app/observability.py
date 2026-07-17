"""Observability wiring for watertwin-api.

Installs the shared observability stack (JSON logging, correlation ids, HTTP
metrics, ``/metrics`` and OpenTelemetry tracing) and registers scrape-time
callbacks that publish this service's domain gauges:

* ``watertwin_audit_chain_length`` -- number of events in the tamper-evident
  audit hash chain;
* ``watertwin_buffer_depth`` (buffer=``recommendations``) -- advisory
  recommendation cards currently held;
* ``watertwin_ingest_lag_seconds`` -- age of the newest telemetry sample from
  the active (read-only) source.

Everything here is read-only observation; no control-write path exists.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from watertwin_observability import (
    AUDIT_CHAIN_LENGTH,
    BUFFER_DEPTH,
    INGEST_LAG,
    instrument_service,
    register_scrape_callback,
)

from . import config

logger = logging.getLogger("watertwin.observability")

_RECO_BUFFER = "recommendations"


def _parse_iso(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str):
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _ingest_lag_seconds(resolution: Any) -> Optional[float]:
    """Age (seconds) of the newest reading from a synthetic source.

    Live-reads only the synthetic source (cheap, side-effect free); for real OT
    connectors a scrape must not trigger a device read, so their lag is reported
    from the last app-recorded ingest instead (0 until one occurs).
    """
    if getattr(resolution, "active", None) != "synthetic":
        return 0.0
    try:
        readings = resolution.source.read_latest()
    except Exception:  # pragma: no cover - synthetic never raises
        return None
    latest: Optional[datetime] = None
    for reading in readings:
        parsed = _parse_iso(getattr(reading, "timestamp", None))
        if parsed and (latest is None or parsed > latest):
            latest = parsed
    if latest is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - latest).total_seconds())


def setup(
    app: Any,
    *,
    store: Any,
    reco_store: Any,
    get_source_resolution: Callable[[], Any],
) -> None:
    """Instrument ``app`` and register this service's domain-gauge callbacks."""
    instrument_service(app, config.SERVICE_NAME, version=config.SERVICE_VERSION)
    service = config.SERVICE_NAME

    def _scrape() -> None:
        try:
            AUDIT_CHAIN_LENGTH.labels(service=service).set(store.audit_length())
        except Exception:  # pragma: no cover - defensive
            logger.debug("audit-chain-length gauge update failed", exc_info=True)
        try:
            BUFFER_DEPTH.labels(service=service, buffer=_RECO_BUFFER).set(len(reco_store.list()))
        except Exception:  # pragma: no cover - defensive
            logger.debug("buffer-depth gauge update failed", exc_info=True)
        try:
            resolution = get_source_resolution()
            lag = _ingest_lag_seconds(resolution)
            if lag is not None:
                INGEST_LAG.labels(service=service, source=resolution.active).set(lag)
        except Exception:  # pragma: no cover - defensive
            logger.debug("ingest-lag gauge update failed", exc_info=True)

    register_scrape_callback(_scrape)

    # Prime the series so they are present on the very first scrape.
    AUDIT_CHAIN_LENGTH.labels(service=service).set(0)
    BUFFER_DEPTH.labels(service=service, buffer=_RECO_BUFFER).set(0)
    INGEST_LAG.labels(service=service, source="synthetic").set(0.0)
