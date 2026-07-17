"""Tests for the read-only, advisory HTTP API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from watertwin.api.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _telemetry_body() -> dict[str, object]:
    return {
        "feed_pressure_bar": 60.0,
        "permeate_pressure_bar": 0.5,
        "feed_channel_dp_bar": 2.0,
        "feed_flow_m3_per_h": 100.0,
        "permeate_flow_m3_per_h": 45.0,
        "feed_tds_mg_per_l": 35000.0,
        "permeate_tds_mg_per_l": 350.0,
        "temperature_c": 25.0,
    }


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_reports_advisory_read_only(client: TestClient) -> None:
    body = client.get("/").json()
    assert body["control_mode"] == "advisory"
    assert body["read_only"] is True


def test_safety_endpoint(client: TestClient) -> None:
    body = client.get("/safety").json()
    assert body == {
        "control_mode": "advisory",
        "operator_approval_required": True,
        "control_write_enabled": False,
    }


def test_advisory_response_headers_present(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers["x-control-mode"] == "advisory"
    assert response.headers["x-operator-approval-required"] == "true"
    assert response.headers["x-control-write-enabled"] == "false"


def test_analytics_train_computes_metrics(client: TestClient) -> None:
    response = client.post("/analytics/train", json=_telemetry_body())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "preliminary"
    assert body["recovery_fraction"] == pytest.approx(0.45, rel=1e-9)
    assert body["safety"]["control_write_enabled"] is False
    assert "disclaimer" in body


def test_analytics_train_rejects_invalid_body(client: TestClient) -> None:
    bad = _telemetry_body()
    bad["feed_pressure_bar"] = -1.0
    response = client.post("/analytics/train", json=bad)
    assert response.status_code == 422


def test_analytics_train_rejects_non_synthetic_provenance(client: TestClient) -> None:
    bad = _telemetry_body()
    bad["provenance"] = "measured"
    response = client.post("/analytics/train", json=bad)
    assert response.status_code == 422


def test_openapi_document_states_safety_posture(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    description = " ".join(schema["info"]["description"].lower().split())
    assert "advisory" in description
    assert "no control-write code path" in description
    assert "synthetic" in description


def test_no_write_or_control_routes_exist(client: TestClient) -> None:
    allowed_methods = {"GET", "HEAD", "OPTIONS", "POST"}
    forbidden_terms = ("control", "command", "write", "valve", "pump", "plc", "scada")
    for route in client.app.routes:
        methods = getattr(route, "methods", set()) or set()
        assert methods <= allowed_methods, f"Unexpected method on {route.path}: {methods}"
        path = getattr(route, "path", "").lower()
        assert not any(
            term in path for term in forbidden_terms
        ), f"Route path suggests a control action: {path}"
