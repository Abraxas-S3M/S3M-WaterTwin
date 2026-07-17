"""End-to-end API tests via the ASGI transport (no network / server needed)."""

from __future__ import annotations

import asyncio

import httpx
from httpx import ASGITransport

from app.main import app

BASE = "http://testserver"

SEAWATER_SIMULATE = {
    "feed": {"flow_m3h": 100.0, "tds_mg_l": 35000.0, "temperature_c": 25.0, "pressure_bar": 60.0},
    "membrane": {"area_m2": 1200.0},
}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url=BASE)


async def _run_to_completion(client: httpx.AsyncClient, endpoint: str, payload: dict) -> dict:
    resp = await client.post(endpoint, json=payload)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["provenance"] == "simulated"
    assert job["status"] == "preliminary"
    assert job["control_boundary"]["control_write_enabled"] is False
    job_id = job["job_id"]
    for _ in range(200):
        poll = await client.get(f"/api/v1/process/jobs/{job_id}")
        assert poll.status_code == 200
        job = poll.json()
        if job["state"] in ("succeeded", "failed"):
            break
        await asyncio.sleep(0.02)
    assert job["state"] == "succeeded", job
    return job


async def test_health_reports_control_boundary():
    async with _client() as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["service"] == "treatment-sim"
        assert body["control_mode"] == "advisory"
        assert body["operator_approval_required"] is True
        assert body["control_write_enabled"] is False
        assert body["engine"] in ("analytical", "watertap")


async def test_simulate_job_lifecycle():
    async with _client() as client:
        job = await _run_to_completion(
            client, "/api/v1/process/simulate", SEAWATER_SIMULATE
        )
        result = job["result"]
        assert 0.25 <= result["recovery"] <= 0.60
        assert result["permeate_tds_mg_l"] < 35000.0
        assert result["provenance"] == "simulated"


async def test_optimize_returns_feasible_point():
    payload = {
        **SEAWATER_SIMULATE,
        "min_recovery": 0.35,
        "max_permeate_tds_mg_l": 500.0,
        "pressure_bounds_bar": [40.0, 80.0],
    }
    async with _client() as client:
        job = await _run_to_completion(client, "/api/v1/process/optimize", payload)
        result = job["result"]
        assert result["feasible"] is True
        assert result["baseline"]["recovery"] >= 0.35 - 1e-6
        assert result["objective_specific_energy_kwh_m3"] > 0


async def test_membrane_degradation_reduces_flow():
    payload = {**SEAWATER_SIMULATE, "a_retention": 0.8, "b_increase": 1.5}
    async with _client() as client:
        job = await _run_to_completion(
            client, "/api/v1/process/membrane-degradation", payload
        )
        result = job["result"]
        assert result["normalized_permeate_flow"] < 1.0


async def test_job_not_found():
    async with _client() as client:
        resp = await client.get("/api/v1/process/jobs/does-not-exist")
        assert resp.status_code == 404
