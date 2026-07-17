"""Baseline hydraulic behaviour and mass-continuity tests."""

from __future__ import annotations

from simulation_contracts import ScenarioType, SimulationRequest

from app.engine import run_simulation
from app.network import DEMAND_NODES


def test_baseline_returns_pressures_and_flows():
    result = run_simulation(SimulationRequest(scenario=ScenarioType.baseline))

    assert result.provenance == "simulated"
    assert result.status == "preliminary"

    # Pressures for every demand node are present and positive.
    for node in DEMAND_NODES:
        assert node in result.outputs.node_pressure_m
        assert result.outputs.node_pressure_m[node] > 0

    # Flows for the main pipeline and both pumps are reported.
    assert "P-MAIN" in result.outputs.link_flow_m3h
    assert "PU-PROD-1" in result.outputs.link_flow_m3h
    assert "PU-PROD-2" in result.outputs.link_flow_m3h

    # Tank level is reported.
    assert "T-PROD" in result.outputs.tank_level_m

    # Baseline should deliver the full design demand (~560 m3/h).
    assert result.outputs.delivered_flow_m3h > 500


def test_baseline_mass_continuity_holds():
    result = run_simulation(SimulationRequest(scenario=ScenarioType.baseline))
    out = result.outputs
    # supply (reservoir) + tank drainage must equal delivered demand.
    assert out.mass_balance_ok is True
    assert abs(out.mass_balance_error_m3h) <= max(1.0, 0.01 * out.total_demand_m3h)


def test_control_boundary_is_read_only():
    result = run_simulation(SimulationRequest(scenario=ScenarioType.baseline))
    assert result.control_boundary.control_write_enabled is False
    assert result.control_boundary.operator_approval_required is True
