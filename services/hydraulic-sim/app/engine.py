"""WNTR/EPANET hydraulic engine wrapper (read-only what-if).

This module never writes to any control system. It loads the RO-handoff network,
applies a scenario as an *in-memory* modification, runs a single-period EPANET
snapshot via WNTR, and returns a canonical :class:`SimulationResult`.
"""

from __future__ import annotations

import math
import os
import tempfile
from typing import Any, Optional

import wntr

from simulation_contracts import (
    ConstraintViolation,
    LeakLocalization,
    ScenarioDelta,
    ScenarioType,
    SimulationOutputs,
    SimulationRequest,
    SimulationResult,
    ViolationSeverity,
)

from .network import (
    CMH,
    DEMAND_NODES,
    EXCLUDE_VELOCITY_LINKS,
    MAX_VELOCITY_M_S,
    PUMPS,
    REQUIRED_PRESSURE_M,
    load_network,
)


class ScenarioError(ValueError):
    """Raised when a scenario request references an unknown/invalid element."""


def _snapshot(wn) -> dict[str, Any]:
    """Run a single-period EPANET simulation and extract the first timestep.

    EPANET writes intermediate ``.inp``/``.rpt``/``.bin`` files using ``file_prefix``;
    we run inside a throwaway temp directory so nothing is left in the working dir.
    """
    with tempfile.TemporaryDirectory(prefix="epanet-") as tmp:
        prefix = os.path.join(tmp, "sim")
        results = wntr.sim.EpanetSimulator(wn).run_sim(file_prefix=prefix)
    pressure = results.node["pressure"].iloc[0]
    head = results.node["head"].iloc[0]
    demand = results.node["demand"].iloc[0]
    flow = results.link["flowrate"].iloc[0]
    velocity = results.link["velocity"].iloc[0]

    node_pressure = {k: float(v) for k, v in pressure.items()}
    node_head = {k: float(v) for k, v in head.items()}
    link_flow = {k: float(v) / CMH for k, v in flow.items()}
    link_velocity = {k: float(v) for k, v in velocity.items()}

    tank_names = wn.tank_name_list
    tank_level = {}
    for t in tank_names:
        tank = wn.get_node(t)
        tank_level[t] = float(node_head[t] - tank.elevation)

    delivered = sum(float(demand[j]) for j in DEMAND_NODES) / CMH

    # Total supply into the network = sum of reservoir outflows (negative demand).
    total_supply = 0.0
    for r in wn.reservoir_name_list:
        total_supply += -float(demand[r]) / CMH
    # Tanks that are draining also supply the network.
    tank_net = 0.0
    for t in tank_names:
        tank_net += -float(demand[t]) / CMH  # +ve = draining into network

    total_demand = sum(float(demand[j]) for j in DEMAND_NODES) / CMH
    # Mass balance: supply (reservoirs) + tank drainage == demand delivered.
    mass_error = (total_supply + tank_net) - total_demand

    return {
        "node_pressure": node_pressure,
        "node_head": node_head,
        "link_flow": link_flow,
        "link_velocity": link_velocity,
        "tank_level": tank_level,
        "delivered": delivered,
        "total_supply": total_supply,
        "total_demand": total_demand,
        "tank_net": tank_net,
        "mass_error": mass_error,
        "demand": {k: float(v) / CMH for k, v in demand.items()},
    }


def _violations(snap: dict[str, Any]) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []
    for node, p in snap["node_pressure"].items():
        if node in DEMAND_NODES and p < REQUIRED_PRESSURE_M:
            sev = ViolationSeverity.critical if p < REQUIRED_PRESSURE_M * 0.5 else ViolationSeverity.warning
            out.append(
                ConstraintViolation(
                    element_id=node,
                    element_type="node",
                    metric="pressure_m",
                    value=round(p, 3),
                    limit=REQUIRED_PRESSURE_M,
                    severity=sev,
                    description=(
                        f"Delivery pressure {p:.1f} m at {node} is below the "
                        f"{REQUIRED_PRESSURE_M:.0f} m service requirement."
                    ),
                )
            )
    for link, v in snap["link_velocity"].items():
        if link in EXCLUDE_VELOCITY_LINKS:
            continue
        if v > MAX_VELOCITY_M_S:
            out.append(
                ConstraintViolation(
                    element_id=link,
                    element_type="link",
                    metric="velocity_m_s",
                    value=round(v, 3),
                    limit=MAX_VELOCITY_M_S,
                    severity=ViolationSeverity.warning,
                    description=f"Velocity {v:.2f} m/s in {link} exceeds {MAX_VELOCITY_M_S:.1f} m/s.",
                )
            )
    return out


def _round_map(d: dict[str, float], nd: int = 3) -> dict[str, float]:
    return {k: round(v, nd) for k, v in d.items()}


def _apply_scenario(wn, request: SimulationRequest) -> list[str]:
    """Mutate the in-memory network per scenario. Returns extra assumptions."""
    scenario = request.scenario
    params = request.parameters or {}
    assumptions: list[str] = []

    if scenario == ScenarioType.baseline:
        return assumptions

    if scenario == ScenarioType.pump_outage:
        pump_id = params.get("pump_id", PUMPS[-1])
        if pump_id not in wn.pump_name_list:
            raise ScenarioError(f"Unknown pump '{pump_id}'. Known: {wn.pump_name_list}")
        wn.get_link(pump_id).initial_status = "Closed"
        assumptions.append(f"Pump {pump_id} removed from service (outage).")
        return assumptions

    if scenario == ScenarioType.valve_closure:
        valve_id = params.get("valve_id", "CV-HANDOFF")
        setting = params.get("setting")
        if valve_id not in wn.valve_name_list:
            raise ScenarioError(f"Unknown valve '{valve_id}'. Known: {wn.valve_name_list}")
        valve = wn.get_link(valve_id)
        if setting is None:
            valve.initial_status = "Closed"
            assumptions.append(f"Valve {valve_id} fully closed.")
        else:
            valve.initial_setting = float(setting)
            assumptions.append(f"Valve {valve_id} throttled to setting {setting}.")
        return assumptions

    if scenario == ScenarioType.demand_change:
        multiplier = params.get("multiplier")
        node_demands = params.get("node_demands")
        if node_demands:
            for node, dem_cmh in node_demands.items():
                if node not in wn.junction_name_list:
                    raise ScenarioError(f"Unknown demand node '{node}'.")
                wn.get_node(node).demand_timeseries_list[0].base_value = float(dem_cmh) * CMH
            assumptions.append(f"Demand overridden at nodes: {sorted(node_demands)}.")
        elif multiplier is not None:
            for node in DEMAND_NODES:
                wn.get_node(node).demand_timeseries_list[0].base_value *= float(multiplier)
            assumptions.append(f"All distribution demands scaled by {multiplier}x.")
        else:
            raise ScenarioError("demand_change requires 'multiplier' or 'node_demands'.")
        return assumptions

    if scenario == ScenarioType.leak:
        node_id = params.get("node_id", "J-D2")
        if node_id not in wn.junction_name_list:
            raise ScenarioError(f"Unknown leak node '{node_id}'.")
        # Emitter models an orifice leak: q = C * p^0.5 (EPANET emitter).
        area = float(params.get("area_m2", 0.01))
        cd = float(params.get("discharge_coeff", 0.75))
        # Emitter coefficient in SI: C = Cd * A * sqrt(2g); convert to CMH-based inp scaling.
        emitter_si = cd * area * math.sqrt(2 * 9.81)
        wn.get_node(node_id).emitter_coefficient = emitter_si
        assumptions.append(
            f"Leak emitter added at {node_id} (area {area} m^2, Cd {cd})."
        )
        return assumptions

    raise ScenarioError(f"Unsupported scenario '{scenario}'.")


def _confidence(scenario: ScenarioType, snap: dict[str, Any]) -> float:
    """Heuristic confidence: high when mass balance is tight and solution clean."""
    conf = 0.8
    if abs(snap["mass_error"]) > 1.0:
        conf -= 0.2
    if scenario in (ScenarioType.leak,):
        conf -= 0.1  # localization is approximate
    return round(max(0.4, min(0.95, conf)), 2)


def _localize_leak(
    request: SimulationRequest, baseline_snap: dict[str, Any], scenario_snap: dict[str, Any]
) -> LeakLocalization:
    """Rank candidate leak nodes by pressure-drop residual vs baseline."""
    residuals: dict[str, float] = {}
    for node in DEMAND_NODES:
        residuals[node] = baseline_snap["node_pressure"][node] - scenario_snap["node_pressure"][node]
    ranked = sorted(residuals.items(), key=lambda kv: kv[1], reverse=True)
    suspected = ranked[0][0]
    return LeakLocalization(
        suspected_node_id=suspected,
        residual_pressure_m=round(residuals[suspected], 3),
        ranked_candidates=[(n, round(r, 3)) for n, r in ranked],
    )


def _delta(baseline_snap: dict[str, Any], scenario_snap: dict[str, Any]) -> ScenarioDelta:
    p_delta = {
        n: round(scenario_snap["node_pressure"][n] - baseline_snap["node_pressure"][n], 3)
        for n in baseline_snap["node_pressure"]
    }
    f_delta = {
        link: round(scenario_snap["link_flow"][link] - baseline_snap["link_flow"][link], 3)
        for link in baseline_snap["link_flow"]
    }
    base_deliv = baseline_snap["delivered"]
    scen_deliv = scenario_snap["delivered"]
    pct = None
    if abs(base_deliv) > 1e-9:
        pct = round(100.0 * (scen_deliv - base_deliv) / base_deliv, 2)
    return ScenarioDelta(
        delivered_flow_baseline_m3h=round(base_deliv, 3),
        delivered_flow_scenario_m3h=round(scen_deliv, 3),
        delivered_flow_delta_m3h=round(scen_deliv - base_deliv, 3),
        delivered_flow_delta_pct=pct,
        pressure_delta_m=p_delta,
        flow_delta_m3h=f_delta,
        min_pressure_baseline_m=round(min(baseline_snap["node_pressure"][n] for n in DEMAND_NODES), 3),
        min_pressure_scenario_m=round(min(scenario_snap["node_pressure"][n] for n in DEMAND_NODES), 3),
    )


def _outputs_from_snapshot(snap: dict[str, Any]) -> SimulationOutputs:
    mass_ok = abs(snap["mass_error"]) <= max(1.0, 0.01 * max(snap["total_demand"], 1.0))
    return SimulationOutputs(
        node_pressure_m=_round_map(snap["node_pressure"]),
        node_head_m=_round_map(snap["node_head"]),
        link_flow_m3h=_round_map(snap["link_flow"]),
        link_velocity_m_s=_round_map(snap["link_velocity"]),
        tank_level_m=_round_map(snap["tank_level"]),
        delivered_flow_m3h=round(snap["delivered"], 3),
        total_demand_m3h=round(snap["total_demand"], 3),
        total_supply_m3h=round(snap["total_supply"], 3),
        mass_balance_error_m3h=round(snap["mass_error"], 4),
        mass_balance_ok=bool(mass_ok),
    )


BASE_ASSUMPTIONS = [
    "Single-period (steady-state) EPANET snapshot; no extended-period dynamics.",
    "Pressure-dependent demand (required pressure 25 m, minimum 0 m).",
    "Read-only what-if: no control-system writes are performed.",
    "Network is the RO-TRAIN-001 product-water handoff reference model.",
]


def run_simulation(request: SimulationRequest, inp_path: Optional[str] = None) -> SimulationResult:
    """Run a scenario and return a canonical, provenance-tagged result."""
    # Baseline snapshot is always computed so scenarios can be compared.
    baseline_wn = load_network(inp_path)
    baseline_snap = _snapshot(baseline_wn)

    scenario_wn = load_network(inp_path)
    extra_assumptions = _apply_scenario(scenario_wn, request)
    scenario_snap = _snapshot(scenario_wn)

    outputs = _outputs_from_snapshot(scenario_snap)

    if request.scenario != ScenarioType.baseline:
        outputs.delta_vs_baseline = _delta(baseline_snap, scenario_snap)
    if request.scenario == ScenarioType.leak:
        outputs.leak_localization = _localize_leak(request, baseline_snap, scenario_snap)

    result = SimulationResult(
        job_id="",  # set by the caller / job runner
        scenario=request.scenario,
        network_id=request.network_id,
        inputs={
            "scenario": request.scenario.value,
            "network_id": request.network_id,
            "facility_id": request.facility_id,
            "train_id": request.train_id,
            "parameters": request.parameters,
            "requested_outputs": request.requested_outputs,
        },
        outputs=outputs,
        constraint_violations=_violations(scenario_snap),
        confidence=_confidence(request.scenario, scenario_snap),
        assumptions=BASE_ASSUMPTIONS + extra_assumptions,
    )
    return result
