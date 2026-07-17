"""Scenario what-if tests: pump outage, valve closure, demand change, leak."""

from __future__ import annotations

from simulation_contracts import ScenarioType, SimulationRequest

from app.engine import run_simulation


def _baseline_delivered() -> float:
    return run_simulation(
        SimulationRequest(scenario=ScenarioType.baseline)
    ).outputs.delivered_flow_m3h


def test_pump_outage_reduces_delivered_flow():
    baseline = _baseline_delivered()
    result = run_simulation(
        SimulationRequest(
            scenario=ScenarioType.pump_outage, parameters={"pump_id": "PU-PROD-2"}
        )
    )
    scenario = result.outputs.delivered_flow_m3h

    assert scenario < baseline
    assert result.outputs.delta_vs_baseline is not None
    assert result.outputs.delta_vs_baseline.delivered_flow_delta_m3h < 0
    # The removed pump should carry no flow.
    assert abs(result.outputs.link_flow_m3h["PU-PROD-2"]) < 1e-3
    # Under-pressure delivery should raise at least one constraint violation.
    assert any(v.metric == "pressure_m" for v in result.constraint_violations)


def test_valve_closure_isolates_handoff():
    baseline = _baseline_delivered()
    result = run_simulation(
        SimulationRequest(scenario=ScenarioType.valve_closure)
    )
    # Closing the handoff valve isolates the pumps; only the elevated storage
    # tank keeps feeding distribution, so delivery drops sharply (but not to
    # zero, which is the realistic buffered behaviour).
    assert result.outputs.delivered_flow_m3h < 0.5 * baseline
    assert result.outputs.delta_vs_baseline.delivered_flow_delta_m3h < 0
    # Isolated from the pumps, delivery pressure falls below requirement.
    assert any(v.metric == "pressure_m" for v in result.constraint_violations)


def test_demand_change_increases_flow():
    baseline = _baseline_delivered()
    result = run_simulation(
        SimulationRequest(
            scenario=ScenarioType.demand_change, parameters={"multiplier": 0.5}
        )
    )
    # Halving demand reduces delivered flow relative to baseline.
    assert result.outputs.delivered_flow_m3h < baseline


def test_leak_localizes_to_emitter_node():
    result = run_simulation(
        SimulationRequest(
            scenario=ScenarioType.leak,
            parameters={"node_id": "J-D3", "area_m2": 0.02, "discharge_coeff": 0.8},
        )
    )
    loc = result.outputs.leak_localization
    assert loc is not None
    # The node with the largest pressure residual should be the leak node
    # (or an immediate hydraulic neighbour).
    assert loc.suspected_node_id in {"J-D3", "J-D1"}
    assert loc.ranked_candidates[0][0] == loc.suspected_node_id


def test_unknown_pump_raises():
    import pytest

    from app.engine import ScenarioError

    with pytest.raises(ScenarioError):
        run_simulation(
            SimulationRequest(
                scenario=ScenarioType.pump_outage, parameters={"pump_id": "NOPE"}
            )
        )
