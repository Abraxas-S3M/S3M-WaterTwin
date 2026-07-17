"""Tests for the constrained RO energy-optimization physics.

Locks the invariants the value layer depends on: the bounded optimiser lowers
specific energy versus a deliberately off-optimal baseline AND never violates a
constraint bound, the cost helper applies its peak term, and avoidable loss is a
non-negative gap.
"""

from __future__ import annotations

import pytest

from watertwin_engineering import (
    avoidable_energy_loss,
    energy_cost,
    ro_operating_point_optimization,
)
from watertwin_engineering.energy import ESTIMATED, evaluate_operating_point


def _feed() -> dict:
    # A deliberately high baseline pressure so there is headroom to optimise.
    return {
        "tds_mg_l": 45000.0,
        "temperature_c": 26.0,
        "boron_mg_l": 5.0,
        "ph": 7.8,
        "feed_pressure_bar": 70.0,
        "recovery": 0.42,
    }


def _membrane_state() -> dict:
    return {
        "feed_flow_m3h": 500.0,
        "membrane_area_m2": 16000.0,
        "permeability_a_lmh_bar": 3.0,
        "salt_permeability_b_lmh": 0.05,
        "pump_efficiency": 0.80,
        "erd_efficiency": 0.95,
        "pressure_drop_bar": 1.0,
        "npsh_available_m": 6.0,
        "npsh_required_m": 3.0,
    }


def _constraints() -> dict:
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
        "tariff_per_kwh": 0.09,
        "operating_hours_per_day": 24.0,
    }


def _assert_within_bounds(op, c: dict) -> None:
    assert op.feasible
    assert op.binding_constraints == []
    assert c["min_pressure_bar"] - 1e-6 <= op.feed_pressure_bar <= c["max_pressure_bar"] + 1e-6
    assert c["min_recovery"] - 1e-6 <= op.recovery <= c["max_recovery"] + 1e-6
    assert (
        c["min_permeate_flow_m3h"] - 1e-6
        <= op.permeate_flow_m3h
        <= c["max_permeate_flow_m3h"] + 1e-6
    )
    assert op.permeate_tds_mg_l <= c["max_permeate_tds_mg_l"] + 1e-6
    assert op.permeate_boron_mg_l <= c["max_permeate_boron_mg_l"] + 1e-6
    assert op.water_flux_lmh <= c["max_flux_lmh"] + 1e-6
    assert op.npsh_margin_m >= c["min_npsh_margin_m"] - 1e-6


def test_optimization_lowers_sec_versus_baseline() -> None:
    result = ro_operating_point_optimization(_feed(), _membrane_state(), _constraints())
    assert result.optimal.sec_kwh_m3 < result.baseline.sec_kwh_m3
    assert result.sec_reduction_kwh_m3 > 0.0
    assert result.sec_reduction_pct > 0.0
    assert result.provenance == ESTIMATED
    assert result.estimated_energy_saving_kwh_day >= 0.0
    assert result.estimated_cost_saving_per_day >= 0.0


def test_optimization_respects_every_constraint_bound() -> None:
    c = _constraints()
    result = ro_operating_point_optimization(_feed(), _membrane_state(), c)
    _assert_within_bounds(result.optimal, c)


def test_optimization_respects_a_tightened_pressure_ceiling() -> None:
    # Even with a tight pressure ceiling the returned point must be feasible.
    c = _constraints()
    c["max_pressure_bar"] = 60.0
    result = ro_operating_point_optimization(_feed(), _membrane_state(), c)
    _assert_within_bounds(result.optimal, c)
    assert result.optimal.feed_pressure_bar <= 60.0 + 1e-6


def test_optimization_raises_when_no_feasible_point() -> None:
    c = _constraints()
    # Impossible: demand a permeate flow the membrane cannot deliver in-bounds.
    c["min_permeate_flow_m3h"] = 900.0
    with pytest.raises(ValueError, match="No feasible"):
        ro_operating_point_optimization(_feed(), _membrane_state(), c)


def test_energy_cost_applies_peak_term() -> None:
    base = energy_cost(100.0, 0.09)
    peak = energy_cost(100.0, 0.09, peak_flag=True, peak_multiplier=1.5)
    assert base == pytest.approx(9.0)
    assert peak == pytest.approx(13.5)
    with_demand = energy_cost(100.0, 0.09, demand_kw=50.0, demand_charge_per_kw=2.0)
    assert with_demand == pytest.approx(9.0 + 100.0)


def test_avoidable_energy_loss_is_non_negative_gap() -> None:
    assert avoidable_energy_loss(3.5, 3.0) == pytest.approx(0.5)
    # Current cannot beat the optimum: clamped at zero.
    assert avoidable_energy_loss(2.8, 3.0) == 0.0


def test_evaluate_operating_point_flags_binding_constraints() -> None:
    c = _constraints()
    # A far-too-low pressure cannot supply the driving pressure the flux needs.
    op = evaluate_operating_point(_feed(), _membrane_state(), 40.0, 0.50, c)
    assert not op.feasible
    assert "insufficient_pressure" in op.binding_constraints
