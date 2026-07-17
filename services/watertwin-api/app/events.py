"""Advisory service-event wiring for watertwin-api.

This module owns the process-wide :class:`~watertwin_events.EventBus` and the
publish/subscribe wiring for the five advisory service events:

* ``telemetry-ingested``  -- telemetry normalized from a read-only source
* ``alert-raised``        -- a water-quality alert routed for operator review
* ``workorder-created``   -- a predictive-maintenance work order created
* ``config-published``    -- the active telemetry source / tag map published
* ``audit-appended``      -- an event appended to the tamper-evident audit trail

The bus is **advisory / notification only**. Every subject is guarded by
:mod:`watertwin_events.subjects`, so a control command can never be published.
If NATS is not configured or is unreachable the bus degrades gracefully: it
logs, increments a metric, and falls back to direct in-process delivery so the
API keeps serving requests (the primary persistence + audit paths always run
regardless of the bus).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from watertwin_events import (
    ALERT_RAISED,
    AUDIT_APPENDED,
    CONFIG_PUBLISHED,
    EVENT_SUBJECTS,
    TELEMETRY_INGESTED,
    WORKORDER_CREATED,
    EventBus,
    EventEnvelope,
    NatsTransport,
)

from . import config

logger = logging.getLogger("watertwin.events")

FACILITY_ID = "S3M-DESAL-01"
TRAIN_ID = "RO-TRAIN-001"

_bus: Optional[EventBus] = None


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


def get_bus() -> EventBus:
    """Return the process-wide bus, constructing + wiring it on first use."""
    global _bus
    if _bus is None:
        _bus = build_bus()
        register_subscribers(_bus)
        # Attempt to connect; on failure the bus stays in degraded direct mode.
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


def _log_received(envelope: EventEnvelope) -> None:
    """Default in-process subscriber: log every received advisory event.

    This handler is also the direct-call fallback target when the bus is
    degraded -- it is invoked directly by the publisher so downstream reactions
    still happen without a broker.
    """
    logger.info(
        "advisory event received: %s (id=%s source=%s)",
        envelope.subject,
        envelope.event_id,
        envelope.source,
    )


def register_subscribers(bus: EventBus) -> None:
    """Subscribe the default in-process handlers for every advisory subject."""
    for subject in EVENT_SUBJECTS:
        bus.subscribe(subject, _log_received)


# ---------------------------------------------------------------------------
# Publisher helpers (one per advisory event). Each is a thin, safe wrapper: the
# bus itself never raises for an outage, but we still guard against unexpected
# programming errors so a publish can never break a request path.
# ---------------------------------------------------------------------------


def _safe_publish(subject: str, payload: dict[str, Any]) -> None:
    try:
        get_bus().publish(
            subject, payload, facility_id=FACILITY_ID, train_id=TRAIN_ID
        )
    except Exception as exc:  # pragma: no cover - defensive; publish is best-effort
        logger.warning("failed to emit advisory event %s: %s", subject, exc)


def publish_telemetry_ingested(
    *, tag_map: str, mapped: int, rejected: int, total: int
) -> None:
    """Emit ``telemetry-ingested`` after raw telemetry is normalized."""
    _safe_publish(
        TELEMETRY_INGESTED,
        {"tag_map": tag_map, "mapped": mapped, "rejected": rejected, "total": total},
    )


def publish_alert_raised(
    *, code: str, recommendation_id: str, stage: str | None, cause: str
) -> None:
    """Emit ``alert-raised`` when a water-quality alert is routed."""
    _safe_publish(
        ALERT_RAISED,
        {
            "code": code,
            "recommendation_id": recommendation_id,
            "stage": stage,
            "cause": cause,
        },
    )


def publish_workorder_created(*, recommendation_id: str, asset_id: str | None) -> None:
    """Emit ``workorder-created`` when a predictive-maintenance card is created."""
    _safe_publish(
        WORKORDER_CREATED,
        {"recommendation_id": recommendation_id, "asset_id": asset_id},
    )


def publish_config_published(*, active_source: str, requested_source: str, tag_map: str | None,
                             fallback: bool) -> None:
    """Emit ``config-published`` when the active telemetry config is published."""
    _safe_publish(
        CONFIG_PUBLISHED,
        {
            "active_source": active_source,
            "requested_source": requested_source,
            "tag_map": tag_map,
            "fallback": fallback,
        },
    )


def audit_event_sink(event: dict[str, Any]) -> None:
    """Store hook: emit ``audit-appended`` for every appended audit event.

    Wired into :class:`app.store.Store` so the event fires after a successful
    append. Publishes only advisory metadata about the audit record (never a
    control instruction).
    """
    _safe_publish(
        AUDIT_APPENDED,
        {
            "audit_id": event.get("id"),
            "kind": event.get("kind"),
            "actor": event.get("actor"),
            "subject": event.get("subject"),
        },
    )
