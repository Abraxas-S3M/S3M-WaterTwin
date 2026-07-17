"""Tests for the deterministic RO membrane calculations."""

from __future__ import annotations

import pytest

from watertwin_engineering.ro import (
    concentration_factor,
    net_driving_pressure_bar,
    recovery_fraction,
    salt_passage_fraction,
    salt_rejection_fraction,
    specific_energy_consumption_kwh_per_m3,
    temperature_correction_factor,
    water_flux_lmh,
)


def test_net_driving_pressure_expected_value() -> None:
    ndp = net_driving_pressure_bar(
        feed_pressure_bar=60.0,
        permeate_pressure_bar=0.0,
        feed_side_osmotic_bar=30.0,
        permeate_osmotic_bar=0.2,
        feed_channel_dp_bar=2.0,
    )
    # (60 - 1) - 0 - (30 - 0.2) = 29.2
    assert ndp == pytest.approx(29.2, rel=1e-9)


def test_net_driving_pressure_can_be_negative() -> None:
    ndp = net_driving_pressure_bar(
        feed_pressure_bar=20.0,
        permeate_pressure_bar=0.0,
        feed_side_osmotic_bar=30.0,
        permeate_osmotic_bar=0.0,
    )
    assert ndp < 0


def test_net_driving_pressure_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError, match="feed_pressure_bar"):
        net_driving_pressure_bar(-1.0, 0.0, 30.0, 0.0)


def test_water_flux_scales_with_permeability_and_ndp() -> None:
    assert water_flux_lmh(1.0, 29.2) == pytest.approx(29.2, rel=1e-9)
    assert water_flux_lmh(2.0, 10.0) == pytest.approx(20.0, rel=1e-9)


def test_water_flux_clamped_at_zero_for_negative_ndp() -> None:
    assert water_flux_lmh(1.0, -5.0) == 0.0


def test_water_flux_rejects_non_positive_permeability() -> None:
    with pytest.raises(ValueError, match="permeability"):
        water_flux_lmh(0.0, 10.0)


def test_recovery_fraction() -> None:
    assert recovery_fraction(45.0, 100.0) == pytest.approx(0.45, rel=1e-9)


def test_recovery_rejects_bad_flows() -> None:
    with pytest.raises(ValueError, match="feed_flow"):
        recovery_fraction(10.0, 0.0)
    with pytest.raises(ValueError, match="permeate_flow"):
        recovery_fraction(-1.0, 100.0)
    with pytest.raises(ValueError, match="recovery > 1"):
        recovery_fraction(120.0, 100.0)


def test_salt_passage_and_rejection() -> None:
    assert salt_passage_fraction(35000.0, 350.0) == pytest.approx(0.01, rel=1e-9)
    assert salt_rejection_fraction(35000.0, 350.0) == pytest.approx(0.99, rel=1e-9)


def test_salt_passage_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError, match="feed_tds"):
        salt_passage_fraction(0.0, 100.0)
    with pytest.raises(ValueError, match="permeate_tds"):
        salt_passage_fraction(35000.0, -1.0)
    with pytest.raises(ValueError, match="salt passage > 1"):
        salt_passage_fraction(100.0, 200.0)


def test_concentration_factor_expected_value() -> None:
    # r = 0.45, rejection = 0.99 -> CF = (1 - 0.45*0.01) / (1 - 0.45)
    cf = concentration_factor(0.45, 0.99)
    assert cf == pytest.approx(0.9955 / 0.55, rel=1e-9)


def test_concentration_factor_complete_rejection_half_recovery() -> None:
    assert concentration_factor(0.5, 1.0) == pytest.approx(2.0, rel=1e-9)


def test_concentration_factor_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="recovery"):
        concentration_factor(1.0, 0.99)
    with pytest.raises(ValueError, match="salt_rejection"):
        concentration_factor(0.5, 1.5)


def test_temperature_correction_factor_unity_at_reference() -> None:
    assert temperature_correction_factor(25.0) == pytest.approx(1.0, rel=1e-12)


def test_temperature_correction_factor_greater_below_reference() -> None:
    assert temperature_correction_factor(20.0) > 1.0
    assert temperature_correction_factor(30.0) < 1.0


def test_temperature_correction_factor_rejects_bad_coefficient() -> None:
    with pytest.raises(ValueError, match="coefficient_per_c"):
        temperature_correction_factor(20.0, coefficient_per_c=0.0)


def test_specific_energy_consumption_without_erd() -> None:
    sec = specific_energy_consumption_kwh_per_m3(
        feed_pressure_bar=60.0,
        feed_flow_m3_per_h=100.0,
        permeate_flow_m3_per_h=45.0,
        pump_efficiency=0.8,
    )
    assert sec == pytest.approx(4.6296, rel=1e-3)


def test_specific_energy_consumption_with_erd_is_lower() -> None:
    without = specific_energy_consumption_kwh_per_m3(60.0, 100.0, 45.0, 0.8)
    with_erd = specific_energy_consumption_kwh_per_m3(
        60.0, 100.0, 45.0, 0.8, energy_recovery_efficiency=0.9
    )
    assert with_erd < without


def test_specific_energy_consumption_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError, match="feed_flow"):
        specific_energy_consumption_kwh_per_m3(60.0, 0.0, 45.0, 0.8)
    with pytest.raises(ValueError, match="permeate_flow_m3_per_h cannot exceed"):
        specific_energy_consumption_kwh_per_m3(60.0, 40.0, 45.0, 0.8)
    with pytest.raises(ValueError, match="pump_efficiency"):
        specific_energy_consumption_kwh_per_m3(60.0, 100.0, 45.0, 0.0)
    with pytest.raises(ValueError, match="energy_recovery_efficiency"):
        specific_energy_consumption_kwh_per_m3(
            60.0, 100.0, 45.0, 0.8, energy_recovery_efficiency=1.5
        )
