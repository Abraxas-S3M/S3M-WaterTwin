"""Unit tests for the deterministic engineering calculation library.

Each test pins a known engineering value and/or asserts a physical invariant.
The two headline physics sanity checks (seawater osmotic pressure ~27.6 bar and
the temperature-correction-factor direction) are exercised explicitly.
"""

import math

import pytest

from watertwin import calculations as calc
from watertwin.calculations import CalcError


def test_pump_head_from_known_pressure_rise():
    # 1 bar rise on seawater (rho=1025) -> H = 1e5 / (1025 * 9.80665) ~ 9.95 m.
    head = calc.pump_head_m(suction_bar=1.0, discharge_bar=2.0)
    expected = 1e5 / (1025.0 * calc.G)
    assert head == pytest.approx(expected)
    assert head == pytest.approx(9.949, abs=1e-2)


def test_pump_head_reversed_pressure_raises():
    with pytest.raises(CalcError):
        calc.pump_head_m(suction_bar=3.0, discharge_bar=2.0)


def test_hydraulic_power_positive_and_scales_with_flow():
    p1 = calc.hydraulic_power_kw(flow_m3h=100.0, head_m=50.0)
    p2 = calc.hydraulic_power_kw(flow_m3h=200.0, head_m=50.0)
    assert p1 > 0
    assert p2 == pytest.approx(2.0 * p1)


def test_hydraulic_power_pinned_value():
    # rho*g*Q*H / 3.6e6 for 100 m3/h at 50 m head, seawater density.
    expected = 1025.0 * calc.G * 100.0 * 50.0 / 3.6e6
    assert calc.hydraulic_power_kw(100.0, 50.0) == pytest.approx(expected)


def test_efficiencies_clamp_to_unit_interval():
    assert calc.pump_efficiency(hydraulic_kw=50.0, shaft_kw=100.0) == pytest.approx(0.5)
    # Raw ratio > 1 (impossible physically) clamps to 1.
    assert calc.pump_efficiency(hydraulic_kw=150.0, shaft_kw=100.0) == 1.0
    assert calc.wire_to_water_efficiency(60.0, 100.0) == pytest.approx(0.6)
    assert calc.wire_to_water_efficiency(500.0, 100.0) == 1.0
    with pytest.raises(CalcError):
        calc.pump_efficiency(50.0, 0.0)


def test_specific_energy_is_power_over_flow():
    assert calc.specific_energy_kwh_m3(power_kw=300.0, permeate_flow_m3h=100.0) == pytest.approx(3.0)
    with pytest.raises(CalcError):
        calc.specific_energy_kwh_m3(300.0, 0.0)


def test_npsh_margin_difference():
    assert calc.npsh_margin_m(npsh_available_m=8.0, npsh_required_m=5.0) == pytest.approx(3.0)
    # Negative margin is physically meaningful and allowed.
    assert calc.npsh_margin_m(4.0, 6.0) == pytest.approx(-2.0)


def test_recovery_and_concentration_factor_consistency():
    y = calc.recovery(permeate_flow_m3h=45.0, feed_flow_m3h=100.0)
    assert y == pytest.approx(0.45)
    cf = calc.concentration_factor(y)
    assert cf == pytest.approx(1.0 / (1.0 - 0.45))
    assert cf == pytest.approx(1.8181818, abs=1e-5)


def test_impossible_recovery_raises():
    with pytest.raises(CalcError):
        calc.recovery(permeate_flow_m3h=120.0, feed_flow_m3h=100.0)
    with pytest.raises(CalcError):
        calc.concentration_factor(1.0)


def test_salt_rejection_and_passage_sum_to_one():
    feed, perm = 35000.0, 300.0
    r = calc.salt_rejection(feed, perm)
    sp = calc.salt_passage(feed, perm)
    assert r + sp == pytest.approx(1.0)
    assert r == pytest.approx(1.0 - 300.0 / 35000.0)


def test_osmotic_pressure_seawater_sanity():
    # Physics sanity check: 35 000 mg/L at 25 C -> ~27.6 bar.
    pi = calc.osmotic_pressure_bar(tds_mg_l=35000.0, temperature_c=25.0)
    assert 24.0 < pi < 30.0
    assert pi == pytest.approx(27.6, abs=0.5)


def test_net_driving_pressure():
    ndp = calc.net_driving_pressure_bar(
        feed_pressure_bar=60.0,
        permeate_pressure_bar=1.0,
        feed_osmotic_bar=27.6,
        permeate_osmotic_bar=0.2,
    )
    assert ndp == pytest.approx((60.0 - 1.0) - (27.6 - 0.2))


def test_temperature_correction_factor_direction():
    # Physics sanity check: colder normalises UP (>1), warmer normalises DOWN (<1).
    assert calc.temperature_correction_factor(18.0) > 1.0
    assert calc.temperature_correction_factor(40.0) < 1.0
    assert calc.temperature_correction_factor(25.0) == pytest.approx(1.0)
    assert calc.temperature_correction_factor(18.0) > calc.temperature_correction_factor(40.0)


def test_normalized_permeate_flow():
    q = calc.normalized_permeate_flow(
        permeate_flow_m3h=100.0,
        ndp_bar=30.0,
        temperature_c=25.0,
        ref_ndp_bar=30.0,
    )
    # At reference NDP and 25 C, normalisation is a no-op.
    assert q == pytest.approx(100.0)
    with pytest.raises(CalcError):
        calc.normalized_permeate_flow(100.0, 0.0, 25.0, 30.0)


def test_cavitation_index_monotonically_decreasing_in_margin():
    margins = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0]
    values = [
        calc.cavitation_index(npsh_margin_m=m, vibration_mm_s=2.0, suction_bar=1.0)
        for m in margins
    ]
    for earlier, later in zip(values, values[1:]):
        assert later < earlier
    for v in values:
        assert 0.0 <= v <= 1.0


def test_cavitation_index_increases_with_vibration_and_low_suction():
    base = calc.cavitation_index(2.0, 1.0, 1.0)
    more_vibration = calc.cavitation_index(2.0, 6.0, 1.0)
    lower_suction = calc.cavitation_index(2.0, 1.0, 0.2)
    assert more_vibration > base
    assert lower_suction > base


def test_bep_distance():
    assert calc.bep_distance(flow_m3h=120.0, bep_flow_m3h=100.0) == pytest.approx(0.2)
    assert calc.bep_distance(80.0, 100.0) == pytest.approx(0.2)
    with pytest.raises(CalcError):
        calc.bep_distance(80.0, 0.0)


def test_mass_balance_error_bounds():
    assert calc.mass_balance_error(feed_flow_m3h=100.0, permeate_flow_m3h=45.0, brine_flow_m3h=55.0) == 0.0
    err = calc.mass_balance_error(100.0, 45.0, 50.0)
    assert err == pytest.approx(0.05)
    assert err >= 0.0
    with pytest.raises(CalcError):
        calc.mass_balance_error(0.0, 45.0, 55.0)


def test_energy_recovery_efficiency_bounds():
    eta = calc.energy_recovery_efficiency(
        hp_feed_out_bar=58.0,
        lp_feed_in_bar=2.0,
        hp_brine_in_bar=59.0,
        brine_out_bar=1.0,
    )
    assert 0.0 <= eta <= 1.0
    assert eta == pytest.approx((58.0 - 2.0) / (59.0 - 1.0))
    with pytest.raises(CalcError):
        calc.energy_recovery_efficiency(58.0, 2.0, 1.0, 59.0)


def test_brine_salt_load():
    # 100 m3/h at 60 000 mg/L -> 100 * 60000 / 1000 = 6000 kg/h.
    assert calc.brine_salt_load_kg_h(100.0, 60000.0) == pytest.approx(6000.0)


def test_contaminant_removal_pct_known_pair():
    assert calc.contaminant_removal_pct(feed_conc=100.0, product_conc=1.0) == pytest.approx(99.0)
    with pytest.raises(CalcError):
        calc.contaminant_removal_pct(0.0, 1.0)


def test_calc_registry_lists_functions_with_units_and_domain():
    registry = calc.calc_registry()
    assert isinstance(registry, list)
    ids = {entry["id"] for entry in registry}
    # Registry ids must correspond to real callables in the module.
    for entry in registry:
        assert {"id", "units", "domain"} <= entry.keys()
        assert callable(getattr(calc, entry["id"]))
    assert "osmotic_pressure_bar" in ids
    assert "cavitation_index" in ids


def test_version_is_set():
    import watertwin

    assert watertwin.__version__ == "0.1.0"


def test_math_import_available_smoke():
    # Guard against accidental removal of math usage in the module under test.
    assert math.isclose(calc.temperature_correction_factor(25.0), 1.0)
