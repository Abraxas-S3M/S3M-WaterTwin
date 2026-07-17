"""Integration tests for the WaterTwin FastAPI service (TestClient)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from watertwin import __version__
from watertwin.app import app


@pytest.fixture()
def client():
    # Using TestClient as a context manager runs the lifespan (telemetry loop,
    # store priming, etc.).
    with TestClient(app) as c:
        yield c


def test_health_exposes_control_write_disabled(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["db_connected"] is False
    assert body["control_mode"] == "advisory"
    assert body["control_write_enabled"] is False


def test_assets_returns_at_least_14(client):
    resp = client.get("/api/v1/assets")
    assert resp.status_code == 200
    assets = resp.json()["assets"]
    assert len(assets) >= 14
    ids = {a["id"] for a in assets}
    assert "HPP-001" in ids


def test_status_carries_boundary(client):
    resp = client.get("/api/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["asset_count"] >= 14
    assert body["control_boundary"]["control_write_enabled"] is False


def test_telemetry_latest_is_primed(client):
    resp = client.get("/api/v1/telemetry/latest")
    assert resp.status_code == 200
    readings = resp.json()["readings"]
    assert len(readings) >= 14


def test_health_and_anomaly_endpoints(client):
    health = client.get("/api/v1/analytics/health/HPP-001")
    assert health.status_code == 200
    assert health.json()["control_boundary"]["control_write_enabled"] is False

    anomaly = client.get("/api/v1/analytics/anomaly/HPP-001")
    assert anomaly.status_code == 200
    assert anomaly.json()["method"] == "zscore"


def test_generate_recommendation_pending_with_boundary(client):
    resp = client.post("/api/v1/recommendations/generate/HPP-001")
    assert resp.status_code == 200
    card = resp.json()
    assert card["approval_status"] == "pending"
    assert card["asset_id"] == "HPP-001"
    assert card["control_boundary"]["control_write_enabled"] is False
    assert card["recommended_actions"]


def test_decision_approves_and_writes_audit(client):
    gen = client.post("/api/v1/recommendations/generate/HPP-001")
    rec_id = gen.json()["id"]

    decision = client.post(
        f"/api/v1/recommendations/{rec_id}/decision",
        json={"status": "approved", "actor": "operator@plant"},
    )
    assert decision.status_code == 200
    decided = decision.json()
    assert decided["approval_status"] == "approved"
    assert decided["decided_by"] == "operator@plant"
    assert decided["decided_at"] is not None

    audit = client.get("/api/v1/audit").json()["events"]
    event_types = {e["event_type"] for e in audit}
    assert "recommendation.generated" in event_types
    assert "recommendation.decision" in event_types
    decision_events = [e for e in audit if e["event_type"] == "recommendation.decision"]
    assert any(e["subject"] == rec_id for e in decision_events)


def test_decision_rejects_invalid_status(client):
    gen = client.post("/api/v1/recommendations/generate/HPP-002")
    rec_id = gen.json()["id"]
    resp = client.post(
        f"/api/v1/recommendations/{rec_id}/decision",
        json={"status": "maybe", "actor": "op"},
    )
    assert resp.status_code == 422


def test_unknown_asset_returns_404(client):
    assert client.get("/api/v1/assets/NOPE-999").status_code == 404


def test_scenario_and_reset(client):
    resp = client.post("/api/v1/scenario", json={"scenario": "degrade"})
    assert resp.status_code == 200
    assert resp.json()["scenario"] == "degrade"

    bad = client.post("/api/v1/scenario", json={"scenario": "bogus"})
    assert bad.status_code == 422

    reset = client.post("/api/v1/reset")
    assert reset.status_code == 200
    assert reset.json()["scenario"] == "normal"


def test_root_serves_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "WaterTwin" in resp.text
