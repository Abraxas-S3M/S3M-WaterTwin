"""Unit tests for the scenario-report endpoint and operator-decision / audit flow.

These use an in-process fake hydraulic client so they run without a live
hydraulic-sim (no EPANET dependency) and cover the Phase 10 additions:
downloadable reports, approval decisions, audit trail, and reset.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from simulation_contracts import (
    ConstraintViolation,
    ScenarioDelta,
    ScenarioType,
    SimulationOutputs,
    SimulationResult,
    ViolationSeverity,
)


class FakeHydraulicClient:
    """Minimal stand-in for HydraulicSimClient returning deterministic results."""

    def health(self) -> dict:
        return {"status": "healthy", "service": "hydraulic-sim"}

    def network_info(self) -> dict:
        return {"train_id": "RO-TRAIN-001", "pumps": ["PU-PROD-1", "PU-PROD-2"]}

    def run(
        self,
        scenario: ScenarioType,
        parameters=None,
        facility_id: str = "S3M-DESAL-01",
        train_id: str = "RO-TRAIN-001",
        requested_by=None,
    ) -> SimulationResult:
        if scenario == ScenarioType.baseline:
            return SimulationResult(
                job_id="sim-baseline01",
                scenario=ScenarioType.baseline,
                outputs=SimulationOutputs(delivered_flow_m3h=100.0),
                confidence=0.8,
                assumptions=["steady-state demand"],
            )
        delta = ScenarioDelta(
            delivered_flow_baseline_m3h=100.0,
            delivered_flow_scenario_m3h=70.0,
            delivered_flow_delta_m3h=-30.0,
            delivered_flow_delta_pct=-30.0,
            min_pressure_baseline_m=30.0,
            min_pressure_scenario_m=22.0,
        )
        return SimulationResult(
            job_id="sim-scenario01",
            scenario=scenario,
            outputs=SimulationOutputs(delivered_flow_m3h=70.0, delta_vs_baseline=delta),
            constraint_violations=[
                ConstraintViolation(
                    element_id="J-D2",
                    element_type="node",
                    metric="pressure_m",
                    value=22.0,
                    limit=25.0,
                    severity=ViolationSeverity.warning,
                    description="Handoff pressure below required minimum.",
                )
            ],
            confidence=0.7,
            assumptions=["steady-state demand", "single duty pump offline"],
        )


@pytest.fixture()
def api_client():
    from app.main import app

    app.state.hydraulic_client = FakeHydraulicClient()
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        yield c


def _run_scenario(api_client) -> dict:
    resp = api_client.post(
        "/api/v1/simulation-center/run",
        json={"scenario": "pump_outage", "parameters": {"pump_id": "PU-PROD-2"}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_health_reports_db_and_boundary(api_client):
    body = api_client.get("/health").json()
    assert body["control_write_enabled"] is False
    assert body["operator_approval_required"] is True
    assert "db_connected" in body  # in-memory fallback -> False here
    assert body["db_connected"] is False


def test_scenario_report_is_downloadable_with_provenance_and_boundary_footer(api_client):
    run = _run_scenario(api_client)
    job_id = run["scenario_result"]["job_id"]

    resp = api_client.post(f"/api/v1/reports/scenario/{job_id}")
    assert resp.status_code == 200, resp.text

    # Downloadable attachment.
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    assert job_id in resp.headers["content-disposition"]

    doc = resp.text
    # Baseline vs scenario + impacts.
    assert "Baseline vs scenario" in doc
    assert "Delivered flow" in doc
    assert "Impacts" in doc
    # Recommended response + confidence.
    assert "Recommended response" in doc
    assert "Confidence" in doc
    # Provenance carried through.
    assert "Provenance" in doc
    assert "simulated" in doc
    assert "preliminary" in doc
    # Boundary footer (mandatory).
    assert "Control boundary" in doc
    assert "control_write_enabled: `false`" in doc
    assert "control_mode: `advisory`" in doc


def test_report_unknown_job_returns_404(api_client):
    resp = api_client.post("/api/v1/reports/scenario/does-not-exist")
    assert resp.status_code == 404


def test_decision_approve_updates_status_and_audits(api_client):
    run = _run_scenario(api_client)
    rec_id = run["recommendation"]["recommendation_id"]

    resp = api_client.post(
        f"/api/v1/recommendations/{rec_id}/decision",
        json={"status": "approved", "actor": "operator-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["approval_status"] == "approved"

    events = api_client.get("/api/v1/audit").json()["events"]
    kinds = {e["kind"] for e in events}
    assert "recommendation.decision" in kinds
    assert "scenario.run" in kinds


def test_decision_rejects_invalid_status(api_client):
    run = _run_scenario(api_client)
    rec_id = run["recommendation"]["recommendation_id"]
    resp = api_client.post(
        f"/api/v1/recommendations/{rec_id}/decision",
        json={"status": "engage-pump", "actor": "x"},
    )
    assert resp.status_code == 422


def test_reset_clears_runs_and_audit(api_client):
    run = _run_scenario(api_client)
    job_id = run["scenario_result"]["job_id"]
    assert api_client.post("/api/v1/reset").status_code == 200
    # Report can no longer be generated for the cleared run.
    assert api_client.post(f"/api/v1/reports/scenario/{job_id}").status_code == 404
