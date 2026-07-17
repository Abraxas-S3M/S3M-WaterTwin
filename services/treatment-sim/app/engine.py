"""Simulation engine dispatcher.

Chooses the WaterTAP/IDAES flowsheet when available (in-container, with ipopt)
and otherwise falls back to the analytical model. Implements the four RO
operations (baseline, optimize, sensitivity, membrane degradation) on top of a
single ``_baseline`` primitive so every operation uses the same physics path.
"""

from __future__ import annotations

import logging

from simulation_contracts import (
    DegradationResult,
    MembraneDegradationRequest,
    OptimizeRequest,
    OptimizeResult,
    ROBaselineResult,
    SensitivityPoint,
    SensitivityRequest,
    SimulateRequest,
    SensitivitySweep,
)

from . import ro_model, watertap_engine

logger = logging.getLogger("treatment-sim.engine")

_ALLOWED_SWEEP_VARS = {
    "feed_tds_mg_l",
    "feed_temperature_c",
    "feed_pressure_bar",
}


def active_engine() -> str:
    return watertap_engine.engine_status()


def _baseline(
    feed_flow_m3h: float,
    feed_tds_mg_l: float,
    feed_pressure_bar: float,
    membrane_area_m2: float,
    a_lmh_bar: float,
    b_lmh: float,
    temperature_c: float,
    pump_efficiency: float,
    erd_efficiency: float,
    use_erd: bool,
    pressure_drop_bar: float,
) -> ROBaselineResult:
    """Run one baseline RO solve, preferring WaterTAP with analytical fallback."""
    kwargs = dict(
        feed_flow_m3h=feed_flow_m3h,
        feed_tds_mg_l=feed_tds_mg_l,
        feed_pressure_bar=feed_pressure_bar,
        membrane_area_m2=membrane_area_m2,
        a_lmh_bar=a_lmh_bar,
        b_lmh=b_lmh,
        temperature_c=temperature_c,
        pump_efficiency=pump_efficiency,
        erd_efficiency=erd_efficiency,
        use_erd=use_erd,
        pressure_drop_bar=pressure_drop_bar,
    )
    if watertap_engine.solver_available():
        try:
            return watertap_engine.simulate_ro_watertap(**kwargs)
        except Exception as exc:  # pragma: no cover - container-only path
            logger.warning("WaterTAP solve failed, using analytical fallback: %s", exc)
    return ro_model.simulate_ro(**kwargs)


def run_simulate(req: SimulateRequest) -> ROBaselineResult:
    return _baseline(
        feed_flow_m3h=req.feed.flow_m3h,
        feed_tds_mg_l=req.feed.tds_mg_l,
        feed_pressure_bar=req.feed.pressure_bar,
        membrane_area_m2=req.membrane.area_m2,
        a_lmh_bar=req.membrane.a_lmh_bar,
        b_lmh=req.membrane.b_lmh,
        temperature_c=req.feed.temperature_c,
        pump_efficiency=req.operating.pump_efficiency,
        erd_efficiency=req.operating.erd_efficiency,
        use_erd=req.operating.use_erd,
        pressure_drop_bar=req.operating.pressure_drop_bar,
    )


def run_optimize(req: OptimizeRequest) -> OptimizeResult:
    """Minimize specific energy over applied pressure subject to constraints."""
    low, high = req.pressure_bounds_bar
    steps = 64
    best: tuple[float, ROBaselineResult] | None = None
    best_feasible: tuple[float, ROBaselineResult] | None = None

    for i in range(steps + 1):
        p = low + (high - low) * i / steps
        res = _baseline(
            feed_flow_m3h=req.feed.flow_m3h,
            feed_tds_mg_l=req.feed.tds_mg_l,
            feed_pressure_bar=p,
            membrane_area_m2=req.membrane.area_m2,
            a_lmh_bar=req.membrane.a_lmh_bar,
            b_lmh=req.membrane.b_lmh,
            temperature_c=req.feed.temperature_c,
            pump_efficiency=req.operating.pump_efficiency,
            erd_efficiency=req.operating.erd_efficiency,
            use_erd=req.operating.use_erd,
            pressure_drop_bar=req.operating.pressure_drop_bar,
        )
        feasible = (
            res.recovery >= req.min_recovery
            and res.permeate_tds_mg_l <= req.max_permeate_tds_mg_l
        )
        if feasible:
            if best_feasible is None or res.specific_energy_kwh_m3 < best_feasible[1].specific_energy_kwh_m3:
                best_feasible = (p, res)
        if best is None or res.specific_energy_kwh_m3 < best[1].specific_energy_kwh_m3:
            best = (p, res)

    chosen = best_feasible if best_feasible is not None else best
    assert chosen is not None
    p_opt, res = chosen
    return OptimizeResult(
        optimal_pressure_bar=p_opt,
        baseline=res,
        feasible=best_feasible is not None,
        objective_specific_energy_kwh_m3=res.specific_energy_kwh_m3,
        constraints_report={
            "min_recovery": req.min_recovery,
            "achieved_recovery": res.recovery,
            "max_permeate_tds_mg_l": req.max_permeate_tds_mg_l,
            "achieved_permeate_tds_mg_l": res.permeate_tds_mg_l,
        },
        engine=res.engine,
    )


def _sensitivity_point(req: SensitivityRequest, value: float) -> ROBaselineResult:
    var = req.sweep.variable
    tds = req.feed.tds_mg_l
    temp = req.feed.temperature_c
    pressure = req.feed.pressure_bar
    if var == "feed_tds_mg_l":
        tds = value
    elif var == "feed_temperature_c":
        temp = value
    elif var == "feed_pressure_bar":
        pressure = value
    return _baseline(
        feed_flow_m3h=req.feed.flow_m3h,
        feed_tds_mg_l=tds,
        feed_pressure_bar=pressure,
        membrane_area_m2=req.membrane.area_m2,
        a_lmh_bar=req.membrane.a_lmh_bar,
        b_lmh=req.membrane.b_lmh,
        temperature_c=temp,
        pump_efficiency=req.operating.pump_efficiency,
        erd_efficiency=req.operating.erd_efficiency,
        use_erd=req.operating.use_erd,
        pressure_drop_bar=req.operating.pressure_drop_bar,
    )


def run_sensitivity(req: SensitivityRequest):
    if req.sweep.variable not in _ALLOWED_SWEEP_VARS:
        raise ValueError(
            f"Unknown sweep variable {req.sweep.variable!r}; "
            f"expected one of {sorted(_ALLOWED_SWEEP_VARS)}"
        )
    from simulation_contracts import SensitivityResult

    sweep: SensitivitySweep = req.sweep
    points: list[SensitivityPoint] = []
    engine_label = "analytical"
    for i in range(sweep.steps):
        value = sweep.start + (sweep.stop - sweep.start) * i / (sweep.steps - 1)
        res = _sensitivity_point(req, value)
        engine_label = res.engine
        points.append(SensitivityPoint(value=value, result=res))
    return SensitivityResult(
        variable=sweep.variable, points=points, engine=engine_label
    )


def run_membrane_degradation(req: MembraneDegradationRequest) -> DegradationResult:
    baseline = _baseline(
        feed_flow_m3h=req.feed.flow_m3h,
        feed_tds_mg_l=req.feed.tds_mg_l,
        feed_pressure_bar=req.feed.pressure_bar,
        membrane_area_m2=req.membrane.area_m2,
        a_lmh_bar=req.membrane.a_lmh_bar,
        b_lmh=req.membrane.b_lmh,
        temperature_c=req.feed.temperature_c,
        pump_efficiency=req.operating.pump_efficiency,
        erd_efficiency=req.operating.erd_efficiency,
        use_erd=req.operating.use_erd,
        pressure_drop_bar=req.operating.pressure_drop_bar,
    )
    aged = _baseline(
        feed_flow_m3h=req.feed.flow_m3h,
        feed_tds_mg_l=req.feed.tds_mg_l,
        feed_pressure_bar=req.feed.pressure_bar,
        membrane_area_m2=req.membrane.area_m2,
        a_lmh_bar=req.membrane.a_lmh_bar * req.a_retention,
        b_lmh=req.membrane.b_lmh * req.b_increase,
        temperature_c=req.feed.temperature_c,
        pump_efficiency=req.operating.pump_efficiency,
        erd_efficiency=req.operating.erd_efficiency,
        use_erd=req.operating.use_erd,
        pressure_drop_bar=req.operating.pressure_drop_bar,
    )
    normalized = (
        aged.permeate_flow_m3h / baseline.permeate_flow_m3h
        if baseline.permeate_flow_m3h > 1e-9
        else 0.0
    )
    return DegradationResult(
        baseline=baseline,
        aged=aged,
        normalized_permeate_flow=normalized,
        permeate_tds_change_mg_l=aged.permeate_tds_mg_l - baseline.permeate_tds_mg_l,
        specific_energy_change_kwh_m3=(
            aged.specific_energy_kwh_m3 - baseline.specific_energy_kwh_m3
        ),
        engine=baseline.engine,
    )
