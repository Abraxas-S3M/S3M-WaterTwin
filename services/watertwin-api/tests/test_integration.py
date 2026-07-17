"""End-to-end integration: watertwin-api -> hydraulic-sim -> recommendation."""

from __future__ import annotations


def test_health_exposes_control_boundary(client):
    body = client.get("/health").json()
    assert body["status"] == "healthy"
    assert body["control_write_enabled"] is False
    assert body["operator_approval_required"] is True
    assert body["hydraulic_sim_reachable"] is True


def test_network_info_proxied(client):
    info = client.get("/api/v1/simulation-center/network").json()
    assert "PU-PROD-1" in info["pumps"]
    assert info["train_id"] == "RO-TRAIN-001"


def test_pump_outage_run_attaches_simulation_id_to_recommendation(client):
    resp = client.post(
        "/api/v1/simulation-center/run",
        json={
            "scenario": "pump_outage",
            "parameters": {"pump_id": "PU-PROD-2"},
            "create_recommendation": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()

    # Job completed and result persisted with correct provenance/status.
    scenario = body["scenario_result"]
    assert scenario["provenance"] == "simulated"
    assert scenario["status"] == "preliminary"

    # Pump outage reduces delivered flow vs baseline.
    comp = body["comparison"]
    assert comp["delivered_flow_scenario_m3h"] < comp["delivered_flow_baseline_m3h"]
    assert comp["delivered_flow_delta_m3h"] < 0

    # A recommendation was created and the simulation_id is attached to evidence.
    reco = body["recommendation"]
    assert reco is not None
    sim_id = scenario["job_id"]
    assert sim_id in reco["evidence"]["simulation_ids"]

    # Control-boundary fields present and read-only on both the run and the card.
    assert body["control_boundary"]["control_write_enabled"] is False
    assert reco["control_boundary"]["control_write_enabled"] is False

    # The persisted recommendation can be fetched back with the sim id intact.
    rid = reco["recommendation_id"]
    fetched = client.get(f"/api/v1/recommendations/{rid}").json()
    assert sim_id in fetched["evidence"]["simulation_ids"]


def test_leak_run_creates_localized_recommendation(client):
    resp = client.post(
        "/api/v1/simulation-center/run",
        json={"scenario": "leak", "parameters": {"node_id": "J-D2"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    reco = body["recommendation"]
    assert reco is not None
    assert body["scenario_result"]["outputs"]["leak_localization"] is not None
    assert len(reco["evidence"]["simulation_ids"]) >= 1
