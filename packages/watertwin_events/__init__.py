"""Advisory service event bus for S3M-WaterTwin.

A small, shared publish/subscribe layer used across services to emit and react
to **advisory / notification** service events -- telemetry-ingested,
alert-raised, workorder-created, config-published, audit-appended -- over NATS,
with graceful degradation to direct in-process delivery when the bus is
unavailable.

Design guarantees (see the submodules for detail):

* **Advisory-only control boundary.** The bus carries notifications about things
  that already happened; it can never carry a control command. Subjects are
  validated by :func:`assert_advisory_subject` and the shipped
  :data:`EVENT_SUBJECTS` are scanned for forbidden control verbs by a guard test.
* **Graceful degradation.** If NATS is not configured or unreachable, the bus
  logs, increments a metric, and falls back to direct in-process delivery so the
  calling service keeps working.

Typical use::

    from watertwin_events import EventBus, NatsTransport, ALERT_RAISED

    bus = EventBus(source="watertwin-api", transport=NatsTransport(url))
    bus.connect()  # degrades gracefully if the broker is down
    bus.subscribe(ALERT_RAISED, handle_alert)
    bus.publish(ALERT_RAISED, {"code": "BORON_HIGH"})
"""

from __future__ import annotations

from .bus import EventBus, EventHandler
from .envelope import EventControlBoundary, EventEnvelope, build_envelope
from .metrics import BusMetrics
from .subjects import (
    ALERT_RAISED,
    AUDIT_APPENDED,
    CONFIG_PUBLISHED,
    EVENT_SUBJECTS,
    FORBIDDEN_CONTROL_VERBS,
    SUBJECT_ROOT,
    TELEMETRY_INGESTED,
    WORKORDER_CREATED,
    ControlCommandOnBusError,
    assert_advisory_subject,
    event_type_of,
    forbidden_verbs_in,
    is_advisory_subject,
    tokenize_subject,
)
from .transport import InProcessTransport, NatsTransport, Transport

__all__ = [
    # bus
    "EventBus",
    "EventHandler",
    # envelope
    "EventEnvelope",
    "EventControlBoundary",
    "build_envelope",
    # metrics
    "BusMetrics",
    # transports
    "Transport",
    "InProcessTransport",
    "NatsTransport",
    # subjects + guard
    "SUBJECT_ROOT",
    "TELEMETRY_INGESTED",
    "ALERT_RAISED",
    "WORKORDER_CREATED",
    "CONFIG_PUBLISHED",
    "AUDIT_APPENDED",
    "EVENT_SUBJECTS",
    "FORBIDDEN_CONTROL_VERBS",
    "ControlCommandOnBusError",
    "assert_advisory_subject",
    "is_advisory_subject",
    "forbidden_verbs_in",
    "tokenize_subject",
    "event_type_of",
]
