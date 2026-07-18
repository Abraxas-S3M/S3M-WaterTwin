"""Advisory service-event wiring for watertwin-ingest.

Publishes three advisory / notification-only events to the shared NATS bus
(``packages/watertwin_events``), reusing the existing guarded
:class:`~watertwin_events.EventEnvelope`:

* ``watertwin.events.ingest.received`` -- a file was received + staged
* ``watertwin.events.ingest.scanned``  -- a staged file passed structural scan
* ``watertwin.events.ingest.failed``   -- intake failed (scan/validation)

The bus is advisory-only: every subject is guarded by
:mod:`watertwin_events.subjects` so a control command can never be published. If
NATS is not configured or unreachable, the bus degrades gracefully to direct
in-process delivery so intake keeps working. No event is ever a control-write
path, and this service never reaches OT.
"""

from __future__ import annotations

import logging
from typing import Any

from watertwin_events import EventBus, EventEnvelope, NatsTransport
from watertwin_events.subjects import SUBJECT_ROOT

from . import config

logger = logging.getLogger("watertwin.ingest.events")

# Advisory ingest subjects (within the guarded ``watertwin.events.*`` namespace;
# none names a forbidden control verb).
INGEST_RECEIVED = f"{SUBJECT_ROOT}.ingest.received"
INGEST_SCANNED = f"{SUBJECT_ROOT}.ingest.scanned"
INGEST_FAILED = f"{SUBJECT_ROOT}.ingest.failed"

INGEST_SUBJECTS = (INGEST_RECEIVED, INGEST_SCANNED, INGEST_FAILED)

_bus: EventBus | None = None


def build_bus() -> EventBus:
    """Construct the event bus (NATS transport when configured, else degraded)."""
    transport = None
    if config.NATS_URL:
        transport = NatsTransport(
            config.NATS_URL,
            connect_timeout=config.NATS_CONNECT_TIMEOUT,
            logger=logger,
        )
    return EventBus(source=config.SERVICE_NAME, transport=transport, logger=logger)


def _log_received(envelope: EventEnvelope) -> None:
    logger.info(
        "advisory event received: %s (id=%s source=%s)",
        envelope.subject,
        envelope.event_id,
        envelope.source,
    )


def register_subscribers(bus: EventBus) -> None:
    """Subscribe default in-process handlers for the ingest subjects."""
    for subject in INGEST_SUBJECTS:
        bus.subscribe(subject, _log_received)


def get_bus() -> EventBus:
    """Return the process-wide bus, constructing + wiring it on first use."""
    global _bus
    if _bus is None:
        _bus = build_bus()
        register_subscribers(_bus)
        _bus.connect()
    return _bus


def set_bus(bus: EventBus) -> None:
    """Inject a bus (used by tests). Does not auto-connect or subscribe."""
    global _bus
    _bus = bus


def reset_bus() -> None:
    """Drop the cached bus (used by tests)."""
    global _bus
    if _bus is not None:
        _bus.close()
    _bus = None


def _safe_publish(subject: str, payload: dict[str, Any], *, facility_id: str | None) -> None:
    try:
        get_bus().publish(subject, payload, facility_id=facility_id)
    except Exception as exc:  # pragma: no cover - defensive; publish is best-effort
        logger.warning("failed to emit advisory event %s: %s", subject, exc)


def publish_ingest_received(
    *, ingest_id: str, tenant_id: str, facility_id: str, sha256: str, size_bytes: int
) -> None:
    """Emit ``ingest.received`` after a file is staged."""
    _safe_publish(
        INGEST_RECEIVED,
        {
            "ingest_id": ingest_id,
            "tenant_id": tenant_id,
            "facility_id": facility_id,
            "sha256": sha256,
            "size_bytes": size_bytes,
        },
        facility_id=facility_id,
    )


def publish_ingest_scanned(
    *, ingest_id: str, tenant_id: str, facility_id: str, detected_class: str, content_type: str
) -> None:
    """Emit ``ingest.scanned`` after a staged file passes the structural scan."""
    _safe_publish(
        INGEST_SCANNED,
        {
            "ingest_id": ingest_id,
            "tenant_id": tenant_id,
            "facility_id": facility_id,
            "detected_class": detected_class,
            "content_type_detected": content_type,
        },
        facility_id=facility_id,
    )


def publish_ingest_failed(
    *, ingest_id: str, tenant_id: str, facility_id: str, code: str, reason: str
) -> None:
    """Emit ``ingest.failed`` when intake fails structural validation."""
    _safe_publish(
        INGEST_FAILED,
        {
            "ingest_id": ingest_id,
            "tenant_id": tenant_id,
            "facility_id": facility_id,
            "code": code,
            "reason": reason,
        },
        facility_id=facility_id,
    )
