"""Integration tests for the advisory service-event bus wiring in watertwin-api.

Exercises the three required behaviours end-to-end through the API:

* **publish/subscribe round-trip** -- hitting the endpoints that raise alerts,
  create work orders, ingest telemetry, publish config, and append audit events
  delivers the matching advisory events to a subscriber over a live (in-process)
  transport.
* **graceful degradation** -- when the bus is unavailable the endpoints still
  succeed and the events are delivered directly in-process (fall back to direct
  calls; log + metric), never breaking the request.
* **guard** -- the subjects the service actually publishes are advisory-only and
  carry no forbidden control verb; the bus refuses a control-command subject.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import events
from app.main import app
from watertwin_events import (
    ALERT_RAISED,
    AUDIT_APPENDED,
    CONFIG_PUBLISHED,
    EVENT_SUBJECTS,
    TELEMETRY_INGESTED,
    WORKORDER_CREATED,
    ControlCommandOnBusError,
    EventBus,
    EventEnvelope,
    InProcessTransport,
    assert_advisory_subject,
    forbidden_verbs_in,
)
from watertwin_events import metrics as m


class _Recorder:
    """Collects every advisory event delivered to it."""

    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    def __call__(self, envelope: EventEnvelope) -> None:
        self.events.append(envelope)

    def subjects(self) -> list[str]:
        return [e.subject for e in self.events]

    def of(self, subject: str) -> list[EventEnvelope]:
        return [e for e in self.events if e.subject == subject]


class _FailingTransport:
    """A transport whose broker is unreachable (connect always fails)."""

    connected = False

    def connect(self) -> None:
        raise ConnectionError("simulated NATS outage")

    def publish(self, subject: str, data: bytes) -> None:  # pragma: no cover - never reached
        raise ConnectionError("simulated NATS outage")

    def subscribe(self, subject, handler) -> None:  # pragma: no cover - never reached
        raise ConnectionError("simulated NATS outage")

    def close(self) -> None:
        pass


def _install_bus(transport) -> tuple[EventBus, _Recorder]:
    recorder = _Recorder()
    bus = EventBus(source="watertwin-api-test", transport=transport)
    bus.connect()
    for subject in EVENT_SUBJECTS:
        bus.subscribe(subject, recorder)
    events.set_bus(bus)
    return bus, recorder


@pytest.fixture()
def connected_bus():
    """A live (in-process) bus injected into the app, with a recorder."""
    bus, recorder = _install_bus(InProcessTransport())
    yield bus, recorder
    events.reset_bus()


@pytest.fixture()
def degraded_bus():
    """A bus whose transport is down, so publishes fall back to direct delivery."""
    bus, recorder = _install_bus(_FailingTransport())
    yield bus, recorder
    events.reset_bus()


# --- publish/subscribe round-trip -------------------------------------------


def test_alert_raised_round_trip(connected_bus):
    bus, recorder = connected_bus
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        recorder.events.clear()
        resp = c.get("/api/v1/water-quality/alerts", params={"fouling": 0.85})
        assert resp.status_code == 200

    alerts = recorder.of(ALERT_RAISED)
    assert alerts, "expected at least one alert-raised event"
    assert alerts[0].event_type == "alert.raised"
    assert alerts[0].payload["code"]
    assert alerts[0].control_boundary.control_write_enabled is False
    # Delivery went through the transport (not degraded).
    assert bus.connected is True
    assert bus.metrics.get(m.PUBLISHED) >= 1
    assert bus.metrics.get(m.DEGRADED_DELIVERIES) == 0


def test_workorder_created_round_trip(connected_bus):
    bus, recorder = connected_bus
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        recorder.events.clear()
        resp = c.get("/api/v1/maintenance/recommendations", params={"fouling": 0.85})
        assert resp.status_code == 200

    workorders = recorder.of(WORKORDER_CREATED)
    assert workorders, "expected at least one workorder-created event"
    assert workorders[0].payload["recommendation_id"]


def test_audit_appended_round_trip(connected_bus):
    _bus, recorder = connected_bus
    with TestClient(app) as c:
        recorder.events.clear()
        # A reset is itself an audited action -> audit-appended fires.
        c.post("/api/v1/reset")

    appended = recorder.of(AUDIT_APPENDED)
    assert appended, "expected an audit-appended event for the reset"
    assert any(e.payload.get("kind") == "system.reset" for e in appended)


def test_telemetry_ingested_round_trip(connected_bus):
    _bus, recorder = connected_bus
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        recorder.events.clear()
        resp = c.post(
            "/api/v1/ingestion/normalize/preview",
            json={"readings": [], "tag_map": "example-plant"},
        )
        assert resp.status_code == 200

    ingested = recorder.of(TELEMETRY_INGESTED)
    assert ingested, "expected a telemetry-ingested event"
    assert ingested[0].payload["tag_map"].startswith("example-plant")
    assert "total" in ingested[0].payload


def test_config_published_on_startup(connected_bus):
    _bus, recorder = connected_bus
    # Startup (lifespan) publishes the active telemetry configuration.
    with TestClient(app):
        pass
    published = recorder.of(CONFIG_PUBLISHED)
    assert published, "expected a config-published event at startup"
    assert published[0].payload["active_source"]


# --- graceful degradation ---------------------------------------------------


def test_endpoints_work_and_deliver_directly_when_bus_down(degraded_bus):
    bus, recorder = degraded_bus
    assert bus.degraded is True  # transport failed to connect

    with TestClient(app) as c:
        c.post("/api/v1/reset")
        recorder.events.clear()
        # The request must still succeed with the bus down.
        resp = c.get("/api/v1/water-quality/alerts", params={"fouling": 0.85})
        assert resp.status_code == 200

    # Events were still delivered -- directly, in-process (the fallback path).
    assert recorder.of(ALERT_RAISED), "alerts should be delivered directly when degraded"
    assert bus.metrics.get(m.DEGRADED_DELIVERIES) >= 1
    assert bus.metrics.get(m.DIRECT_DELIVERIES) >= 1
    assert bus.metrics.get(m.PUBLISHED) == 0


def test_health_and_status_report_bus_state(degraded_bus):
    bus, _recorder = degraded_bus
    with TestClient(app) as c:
        health = c.get("/health").json()
        status = c.get("/api/v1/events/status").json()

    assert health["event_bus"]["degraded"] is True
    assert health["event_bus"]["connected"] is False
    assert status["degraded"] is True
    assert status["control_boundary"]["control_write_enabled"] is False
    assert set(status["subjects"]) == set(EVENT_SUBJECTS)


# --- guard: no control commands on the bus ----------------------------------


def test_service_only_publishes_advisory_subjects():
    """Every subject the service publishes is advisory-only (guard)."""
    for subject in EVENT_SUBJECTS:
        assert_advisory_subject(subject)  # must not raise
        assert forbidden_verbs_in(subject) == set(), subject


def test_bus_rejects_a_control_command_subject(connected_bus):
    bus, _recorder = connected_bus
    with pytest.raises(ControlCommandOnBusError):
        bus.publish("watertwin.events.hpp.setpoint", {"pressure_bar": 65})
