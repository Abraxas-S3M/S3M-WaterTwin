"""API tests for the hydraulic-sim FastAPI service."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _await_job(job_id: str):
    resp = client.get(f"/api/v1/hydraulics/jobs/{job_id}")
    assert resp.status_code == 200
    return resp.json()


def test_health_returns_control_boundary_fields():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["control_mode"] == "advisory"
    assert body["operator_approval_required"] is True
    assert body["control_write_enabled"] is False
    assert body["provenance"] == "simulated"
    assert body["control_boundary"]["control_write_enabled"] is False


def test_baseline_job_completes_and_persists():
    resp = client.post("/api/v1/hydraulics/simulate", json={"scenario": "baseline"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = _await_job(job_id)
    assert job["state"] == "completed"
    result = job["result"]
    assert result["provenance"] == "simulated"
    assert result["status"] == "preliminary"
    assert result["job_id"] == job_id
    assert result["outputs"]["delivered_flow_m3h"] > 500


def test_pump_outage_endpoint_reduces_flow():
    base = client.post("/api/v1/hydraulics/simulate", json={"scenario": "baseline"})
    base_job = _await_job(base.json()["job_id"])
    base_flow = base_job["result"]["outputs"]["delivered_flow_m3h"]

    resp = client.post(
        "/api/v1/hydraulics/pump-outage", json={"parameters": {"pump_id": "PU-PROD-2"}}
    )
    assert resp.status_code == 202
    job = _await_job(resp.json()["job_id"])
    assert job["state"] == "completed"
    assert job["result"]["scenario"] == "pump_outage"
    assert job["result"]["outputs"]["delivered_flow_m3h"] < base_flow


def test_leak_endpoint_localizes():
    resp = client.post(
        "/api/v1/hydraulics/leak", json={"parameters": {"node_id": "J-D2"}}
    )
    job = _await_job(resp.json()["job_id"])
    assert job["state"] == "completed"
    assert job["result"]["outputs"]["leak_localization"] is not None


def test_unknown_job_returns_404():
    resp = client.get("/api/v1/hydraulics/jobs/does-not-exist")
    assert resp.status_code == 404
