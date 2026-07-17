"""Energy Optimization engine (advisory, read-only).

Wraps the constrained RO energy-optimization physics in
:mod:`watertwin_engineering.energy` for the API + dashboard. It computes, for the
reference RO train:

* the min-SEC feasible operating point (optimal HP-pump discharge pressure +
  recovery) subject to flow / product-quality / pressure / cavitation / flux
  constraints, with baseline-vs-optimised specific energy and ESTIMATED energy +
  cost deltas;
* an energy-by-asset breakdown + current-vs-optimal specific energy summary; and
* avoidable specific-energy losses.

Everything here reuses the single canonical RO model + :func:`specific_energy`;
no physics is reimplemented. Every saving / cost figure is an ESTIMATED,
preliminary number on a SYNTHETIC basis -- not a validated or guaranteed saving.
Nothing here writes to any control system.
"""

from __future__ import annotations

from canonical_water_model import (
    DataProvenance,
    EnergyLoss,
    EnergyOptimizationResult,
)
from watertwin_engineering import (
    ro_operating_point_optimization,
)
from watertwin_engineering.energy import ROEnergyOptimization

from .water_quality import INTAKE

#: The HP-pump asset the optimisation setpoint applies to.
HP_PUMP_ASSET_ID = "AST-HPP-01"
CURRENCY = "USD"

#: Economic + operating assumptions (synthetic pilot basis).
TARIFF_PER_KWH = 0.09
OPERATING_HOURS_PER_DAY = 24.0

#: The plant's current (deliberately conservative / off-optimal) operating point.
BASELINE_FEED_PRESSURE_BAR = 68.0
BASELINE_RECOVERY = 0.42


def _feed(fouling: float) -> dict:
    """Reference feed composition + current operating point."""
    return {
        "tds_mg_l": INTAKE["tds_mg_l"],
        "temperature_c": INTAKE["temperature_c"],
        "boron_mg_l": INTAKE["boron_mg_l"],
        "ph": 7.8,
        "feed_pressure_bar": BASELINE_FEED_PRESSURE_BAR,
        "recovery": BASELINE_RECOVERY,
    }


def _membrane_state(fouling: float) -> dict:
    """Membrane/pump parameters, de-rated by ``fouling`` (read-only what-if)."""
    return {
        "feed_flow_m3h": 500.0,
        "membrane_area_m2": 16000.0,
        "permeability_a_lmh_bar": 3.0,
        # Fouling raises salt passage (higher B) and the feed-channel dP.
        "salt_permeability_b_lmh": 0.05 * (1.0 + 3.0 * fouling),
        "membrane_age_factor": max(0.80, 1.0 - 0.20 * fouling),
        "pump_efficiency": 0.80,
        "erd_efficiency": 0.95,
        "pressure_drop_bar": 1.0 * (1.0 + 1.8 * fouling),
        "npsh_available_m": 6.0,
        "npsh_required_m": 3.0,
    }


def _constraints() -> dict:
    """Operating constraints + economic inputs for the optimiser."""
    return {
        "min_permeate_flow_m3h": 180.0,
        "max_permeate_flow_m3h": 280.0,
        "max_permeate_tds_mg_l": 500.0,
        "max_permeate_boron_mg_l": 1.0,
        "min_pressure_bar": 45.0,
        "max_pressure_bar": 75.0,
        "min_recovery": 0.35,
        "max_recovery": 0.52,
        "max_flux_lmh": 22.0,
        "min_npsh_margin_m": 1.0,
        "tariff_per_kwh": TARIFF_PER_KWH,
        "operating_hours_per_day": OPERATING_HOURS_PER_DAY,
        "peak_flag": False,
    }


def optimize(fouling: float) -> ROEnergyOptimization:
    """Run the bounded RO energy optimisation for the reference train."""
    return ro_operating_point_optimization(
        _feed(fouling), _membrane_state(fouling), _constraints()
    )


def optimization_result(fouling: float) -> EnergyOptimizationResult:
    """Optimal setpoint + baseline-vs-optimised SEC + ESTIMATED savings."""
    opt = optimize(fouling)
    o = opt.optimal
    b = opt.baseline
    return EnergyOptimizationResult(
        asset_id=HP_PUMP_ASSET_ID,
        optimal_feed_pressure_bar=o.feed_pressure_bar,
        optimal_recovery=o.recovery,
        baseline_sec_kwh_m3=b.sec_kwh_m3,
        optimized_sec_kwh_m3=o.sec_kwh_m3,
        sec_reduction_kwh_m3=opt.sec_reduction_kwh_m3,
        sec_reduction_pct=opt.sec_reduction_pct,
        permeate_flow_m3h=o.permeate_flow_m3h,
        permeate_tds_mg_l=o.permeate_tds_mg_l,
        permeate_boron_mg_l=o.permeate_boron_mg_l,
        estimated_energy_saving_kwh_day=opt.estimated_energy_saving_kwh_day,
        estimated_cost_saving_per_day=opt.estimated_cost_saving_per_day,
        currency=CURRENCY,
        constraints_respected=o.feasible,
        binding_constraints=o.binding_constraints,
        method=opt.method,
        provenance=DataProvenance.estimated,
    )


def _asset_power_breakdown(opt: ROEnergyOptimization) -> tuple[list[dict], float]:
    """Energy-by-asset breakdown at the optimal operating point (synthetic)."""
    o = opt.optimal
    ms = _membrane_state(0.0)
    pump_eff = ms["pump_efficiency"]
    erd_eff = ms["erd_efficiency"]
    pressure_drop = ms["pressure_drop_bar"]

    feed_flow = o.feed_flow_m3h
    concentrate_flow = feed_flow * (1.0 - o.recovery)
    concentrate_pressure = max(o.feed_pressure_bar - pressure_drop, 0.0)

    # Hydraulic power Q*P/(36*eff) kW; ERD returns part of the concentrate energy.
    gross_kw = feed_flow * o.feed_pressure_bar / (36.0 * pump_eff)
    recovered_kw = erd_eff * concentrate_flow * concentrate_pressure / 36.0
    hp_net_kw = max(gross_kw - recovered_kw, 0.0)

    # Small, fixed balance-of-plant loads (synthetic).
    booster_kw = 24.0
    dosing_kw = 6.0
    aux_kw = 14.0

    breakdown = [
        {"asset_id": HP_PUMP_ASSET_ID, "name": "High-Pressure Pump A (net of ERD)",
         "power_kw": round(hp_net_kw, 2), "provenance": DataProvenance.synthetic.value},
        {"asset_id": "AST-ERD-01", "name": "Energy Recovery Device (recovered)",
         "power_kw": round(-recovered_kw, 2), "provenance": DataProvenance.synthetic.value},
        {"asset_id": "AST-BOOST-01", "name": "Booster / Permeate Pump",
         "power_kw": booster_kw, "provenance": DataProvenance.synthetic.value},
        {"asset_id": "AST-DOSE-01", "name": "Dosing Skid",
         "power_kw": dosing_kw, "provenance": DataProvenance.synthetic.value},
        {"asset_id": "AUX", "name": "Auxiliary / Controls",
         "power_kw": aux_kw, "provenance": DataProvenance.synthetic.value},
    ]
    total = round(hp_net_kw + booster_kw + dosing_kw + aux_kw, 2)
    return breakdown, total


def energy_summary(fouling: float) -> dict:
    """Energy-by-asset + current-vs-optimal SEC summary for the train."""
    opt = optimize(fouling)
    breakdown, total_power = _asset_power_breakdown(opt)
    o = opt.optimal
    b = opt.baseline
    return {
        "energy_by_asset": breakdown,
        "total_power_kw": total_power,
        "current_setpoint": {
            "feed_pressure_bar": b.feed_pressure_bar,
            "recovery": b.recovery,
            "sec_kwh_m3": b.sec_kwh_m3,
            "permeate_flow_m3h": b.permeate_flow_m3h,
        },
        "optimal_setpoint": {
            "feed_pressure_bar": o.feed_pressure_bar,
            "recovery": o.recovery,
            "sec_kwh_m3": o.sec_kwh_m3,
            "permeate_flow_m3h": o.permeate_flow_m3h,
        },
        "current_sec_kwh_m3": b.sec_kwh_m3,
        "optimal_sec_kwh_m3": o.sec_kwh_m3,
        "sec_reduction_kwh_m3": opt.sec_reduction_kwh_m3,
        "sec_reduction_pct": opt.sec_reduction_pct,
        "estimated_cost_saving_per_day": opt.estimated_cost_saving_per_day,
        "currency": CURRENCY,
    }


def losses(fouling: float) -> list[EnergyLoss]:
    """Avoidable specific-energy losses (ESTIMATED, synthetic basis)."""
    opt = optimize(fouling)
    o = opt.optimal
    b = opt.baseline
    hours = OPERATING_HOURS_PER_DAY
    permeate_m3_day = o.permeate_flow_m3h * hours

    out: list[EnergyLoss] = []

    # Primary: current SEC vs best-achievable (optimised) SEC.
    avoidable = opt.sec_reduction_kwh_m3
    avoidable_kwh_day = round(avoidable * permeate_m3_day, 2)
    out.append(
        EnergyLoss(
            label="RO specific-energy vs optimum",
            current_sec_kwh_m3=b.sec_kwh_m3,
            best_achievable_sec_kwh_m3=o.sec_kwh_m3,
            avoidable_loss_kwh_m3=avoidable,
            avoidable_loss_pct=opt.sec_reduction_pct,
            estimated_avoidable_kwh_day=avoidable_kwh_day,
            estimated_avoidable_cost_per_day=opt.estimated_cost_saving_per_day,
            currency=CURRENCY,
            provenance=DataProvenance.estimated,
        )
    )
    return out
