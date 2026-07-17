"""Tests for the advisory service-event bus (:mod:`watertwin_events`).

Covers the three behaviours the feature guarantees:

* **publish/subscribe round-trip** -- a published event reaches subscribers
  through a live transport, with the read-only control boundary intact.
* **graceful degradation** -- when the bus (transport) is unavailable the
  publisher does not raise; it logs, counts a metric, and falls back to direct
  in-process delivery so the caller keeps working.
* **guard** -- every published subject is advisory-only; a subject naming a
  forbidden control verb (a control command) is rejected and can never be put on
  the bus.
"""

from __future__ import annotations

import pytest

from watertwin_events import (
    ALERT_RAISED,
    AUDIT_APPENDED,
    CONFIG_PUBLISHED,
    EVENT_SUBJECTS,
    FORBIDDEN_CONTROL_VERBS,
    SUBJECT_ROOT,
    TELEMETRY_INGESTED,
    WORKORDER_CREATED,
    BusMetrics,
    ControlCommandOnBusError,
    EventBus,
    EventEnvelope,
    InProcessTransport,
    assert_advisory_subject,
    forbidden_verbs_in,
    is_advisory_subject,
)
from watertwin_events import metrics as m

# --- helpers ----------------------------------------------------------------


class _FlakyTransport:
    """A transport that fails on connect (simulates an unreachable broker)."""

    def __init__(self, *, fail_on_connect: bool = True, fail_on_publish: bool = False):
        self._fail_on_connect = fail_on_connect
        self._fail_on_publish = fail_on_publish
        self.connected = False
        self.published: list[tuple[str, bytes]] = []

    def connect(self) -> None:
        if self._fail_on_connect:
            raise ConnectionError("broker unreachable")
        self.connected = True

    def publish(self, subject: str, data: bytes) -> None:
        if self._fail_on_publish:
            raise ConnectionError("publish failed mid-flight")
        self.published.append((subject, data))

    def subscribe(self, subject, handler) -> None:  # pragma: no cover - unused here
        pass

    def close(self) -> None:
        self.connected = False


# --- publish/subscribe round-trip -------------------------------------------


def test_publish_subscribe_round_trip():
    bus = EventBus(source="round-trip", transport=InProcessTransport())
    assert bus.connect() is True
    assert bus.connected is True

    received: list[EventEnvelope] = []
    bus.subscribe(ALERT_RAISED, received.append)

    envelope = bus.publish(
        ALERT_RAISED,
        {"code": "BORON_HIGH"},
        facility_id="S3M-DESAL-01",
        train_id="RO-TRAIN-001",
    )

    assert len(received) == 1
    got = received[0]
    assert got.subject == ALERT_RAISED
    assert got.event_type == "alert.raised"
    assert got.payload == {"code": "BORON_HIGH"}
    assert got.facility_id == "S3M-DESAL-01"
    assert got.source == "round-trip"
    # Advisory control boundary is stamped on the wire.
    assert got.advisory is True
    assert got.control_boundary.control_write_enabled is False
    # Delivery went through the transport, not the degraded fallback.
    assert bus.metrics.get(m.PUBLISHED) == 1
    assert bus.metrics.get(m.BUS_DELIVERIES) == 1
    assert bus.metrics.get(m.DEGRADED_DELIVERIES) == 0
    # The returned envelope matches what subscribers received.
    assert envelope.event_id == got.event_id


def test_round_trip_serializes_through_bytes():
    """The transport carries bytes; subscribers get a faithfully parsed envelope."""
    transport = InProcessTransport()
    bus = EventBus(source="wire", transport=transport)
    bus.connect()

    received: list[EventEnvelope] = []
    bus.subscribe(WORKORDER_CREATED, received.append)
    bus.publish(WORKORDER_CREATED, {"recommendation_id": "rec-1", "asset_id": "AST-HPP-01"})

    assert received[0].payload["recommendation_id"] == "rec-1"
    # Round-trips cleanly through JSON bytes.
    raw = received[0].to_bytes()
    assert EventEnvelope.from_bytes(raw).payload == received[0].payload


def test_multiple_subscribers_all_receive():
    bus = EventBus(source="fanout", transport=InProcessTransport())
    bus.connect()
    a: list[EventEnvelope] = []
    b: list[EventEnvelope] = []
    bus.subscribe(TELEMETRY_INGESTED, a.append)
    bus.subscribe(TELEMETRY_INGESTED, b.append)
    bus.publish(TELEMETRY_INGESTED, {"mapped": 3})
    assert len(a) == 1 and len(b) == 1


# --- graceful degradation ---------------------------------------------------


def test_degrades_when_no_transport_configured():
    """With no transport the bus is degraded and delivers directly."""
    bus = EventBus(source="no-bus")
    assert bus.connect() is False
    assert bus.connected is False
    assert bus.degraded is True

    received: list[EventEnvelope] = []
    bus.subscribe(AUDIT_APPENDED, received.append)

    # Publishing must NOT raise, and must fall back to direct delivery.
    bus.publish(AUDIT_APPENDED, {"kind": "scenario.run"})

    assert len(received) == 1
    assert bus.metrics.get(m.DEGRADED_DELIVERIES) == 1
    assert bus.metrics.get(m.DIRECT_DELIVERIES) == 1
    assert bus.metrics.get(m.PUBLISHED) == 0


def test_degrades_when_transport_connect_fails(caplog):
    """An unreachable broker degrades to direct delivery + logs + metric."""
    transport = _FlakyTransport(fail_on_connect=True)
    bus = EventBus(source="unreachable", transport=transport)

    import logging

    with caplog.at_level(logging.WARNING, logger="watertwin.events"):
        assert bus.connect() is False
    assert any("degrading to direct" in r.message for r in caplog.records)
    assert bus.metrics.get(m.CONNECT_FAILURES) == 1
    assert bus.degraded is True

    received: list[EventEnvelope] = []
    bus.subscribe(ALERT_RAISED, received.append)
    bus.publish(ALERT_RAISED, {"code": "SCALING"})

    assert len(received) == 1  # delivered directly despite the dead broker
    assert bus.metrics.get(m.DEGRADED_DELIVERIES) == 1


def test_degrades_when_publish_fails_after_connect(caplog):
    """A publish error mid-flight falls back to direct delivery (no raise)."""
    transport = _FlakyTransport(fail_on_connect=False, fail_on_publish=True)
    bus = EventBus(source="flaky", transport=transport)
    assert bus.connect() is True
    assert bus.connected is True

    received: list[EventEnvelope] = []
    bus.subscribe(CONFIG_PUBLISHED, received.append)

    import logging

    with caplog.at_level(logging.WARNING, logger="watertwin.events"):
        bus.publish(CONFIG_PUBLISHED, {"active_source": "synthetic"})

    assert len(received) == 1
    assert bus.metrics.get(m.PUBLISH_FAILURES) == 1
    assert bus.metrics.get(m.DEGRADED_DELIVERIES) == 1
    assert any("falling back to direct" in r.message for r in caplog.records)


def test_handler_error_is_isolated():
    """A misbehaving subscriber never breaks the publisher."""
    bus = EventBus(source="isolate", transport=InProcessTransport())
    bus.connect()

    def _boom(_env):
        raise RuntimeError("subscriber blew up")

    good: list[EventEnvelope] = []
    bus.subscribe(ALERT_RAISED, _boom)
    bus.subscribe(ALERT_RAISED, good.append)
    # Must not raise.
    bus.publish(ALERT_RAISED, {"code": "X"})
    assert len(good) == 1
    assert bus.metrics.get(m.HANDLER_ERRORS) == 1


def test_status_snapshot_is_serializable():
    bus = EventBus(source="status", transport=InProcessTransport())
    bus.connect()
    bus.subscribe(ALERT_RAISED, lambda _e: None)
    status = bus.status()
    assert status["source"] == "status"
    assert status["connected"] is True
    assert status["degraded"] is False
    assert ALERT_RAISED in status["subjects"]
    assert isinstance(status["metrics"], dict)


# --- guard: advisory-only / no control commands -----------------------------


def test_all_published_subjects_are_advisory():
    """Every shipped subject must pass the advisory guard (no control verbs)."""
    assert EVENT_SUBJECTS, "expected a non-empty subject registry"
    for subject in EVENT_SUBJECTS:
        assert subject.startswith(f"{SUBJECT_ROOT}.")
        assert is_advisory_subject(subject), subject
        assert forbidden_verbs_in(subject) == set(), subject
        # Must not raise.
        assert_advisory_subject(subject)


@pytest.mark.parametrize(
    "subject",
    [
        "watertwin.events.pump.command",
        "watertwin.events.hpp.setpoint",
        "watertwin.events.valve.open",
        "watertwin.events.valve.close",
        "watertwin.events.pump.start",
        "watertwin.events.pump.stop",
        "watertwin.events.control.write",
        "watertwin.events.generator.dispatch",
        "watertwin.events.actuator.actuate",
        "watertwin.events.system.override",
    ],
)
def test_control_command_subjects_are_rejected(subject):
    """Any subject naming a control verb is refused (advisory-only bus)."""
    assert forbidden_verbs_in(subject), subject
    assert not is_advisory_subject(subject)
    with pytest.raises(ControlCommandOnBusError):
        assert_advisory_subject(subject)


def test_publishing_a_control_subject_raises():
    bus = EventBus(source="guarded", transport=InProcessTransport())
    bus.connect()
    with pytest.raises(ControlCommandOnBusError):
        bus.publish("watertwin.events.pump.command", {"speed": 100})


def test_subscribing_to_a_control_subject_raises():
    bus = EventBus(source="guarded", transport=InProcessTransport())
    bus.connect()
    with pytest.raises(ControlCommandOnBusError):
        bus.subscribe("watertwin.events.hpp.setpoint", lambda _e: None)


def test_subjects_outside_namespace_are_rejected():
    with pytest.raises(ControlCommandOnBusError):
        assert_advisory_subject("some.other.telemetry.ingested")
    with pytest.raises(ControlCommandOnBusError):
        assert_advisory_subject("")


def test_every_forbidden_verb_is_actually_blocked():
    """Sanity: each forbidden verb, used as a subject token, is caught."""
    for verb in FORBIDDEN_CONTROL_VERBS:
        subject = f"{SUBJECT_ROOT}.asset.{verb}"
        assert forbidden_verbs_in(subject), verb
        with pytest.raises(ControlCommandOnBusError):
            assert_advisory_subject(subject)


def test_nats_transport_degrades_when_broker_unreachable():
    """The real NATS transport degrades gracefully against a dead broker."""
    pytest.importorskip("nats")
    from watertwin_events import NatsTransport

    # Port 4 is reserved/unassigned -> connect will fail fast.
    transport = NatsTransport("nats://127.0.0.1:4", connect_timeout=0.5)
    bus = EventBus(source="nats-degrade", transport=transport)

    assert bus.connect() is False
    assert bus.degraded is True
    assert bus.metrics.get(m.CONNECT_FAILURES) == 1

    received: list[EventEnvelope] = []
    bus.subscribe(AUDIT_APPENDED, received.append)
    # Publishing still works via direct delivery despite the dead broker.
    bus.publish(AUDIT_APPENDED, {"kind": "system.reset"})
    assert len(received) == 1
    assert bus.metrics.get(m.DEGRADED_DELIVERIES) == 1
    bus.close()


def test_metrics_counters_are_independent():
    metrics = BusMetrics()
    metrics.inc(m.PUBLISHED, 2)
    metrics.inc(m.HANDLER_ERRORS)
    snap = metrics.snapshot()
    assert snap[m.PUBLISHED] == 2
    assert snap[m.HANDLER_ERRORS] == 1
    metrics.reset()
    assert metrics.snapshot() == {}
