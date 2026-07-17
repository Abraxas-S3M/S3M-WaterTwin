"""Tests for osmotic-pressure estimates."""

from __future__ import annotations

import pytest

from watertwin.engineering.osmotic import (
    osmotic_pressure_bar,
    seawater_osmotic_pressure_bar,
)


def test_zero_tds_gives_zero_pressure() -> None:
    assert osmotic_pressure_bar(0.0, 25.0) == 0.0


def test_seawater_osmotic_pressure_is_in_expected_range() -> None:
    # ~35 g/L seawater at 25 C: van't Hoff (NaCl-equivalent) ~ 29-30 bar.
    pressure = seawater_osmotic_pressure_bar(35000.0, 25.0)
    assert 29.0 <= pressure <= 30.5


def test_pressure_increases_with_tds() -> None:
    low = seawater_osmotic_pressure_bar(20000.0, 25.0)
    high = seawater_osmotic_pressure_bar(45000.0, 25.0)
    assert high > low


def test_pressure_increases_with_temperature() -> None:
    cold = seawater_osmotic_pressure_bar(35000.0, 10.0)
    warm = seawater_osmotic_pressure_bar(35000.0, 30.0)
    assert warm > cold


def test_linear_in_tds() -> None:
    single = seawater_osmotic_pressure_bar(10000.0, 25.0)
    double = seawater_osmotic_pressure_bar(20000.0, 25.0)
    assert double == pytest.approx(2 * single, rel=1e-9)


def test_negative_tds_rejected() -> None:
    with pytest.raises(ValueError, match="tds_mg_per_l"):
        osmotic_pressure_bar(-1.0, 25.0)


def test_below_absolute_zero_rejected() -> None:
    with pytest.raises(ValueError, match="absolute zero"):
        osmotic_pressure_bar(35000.0, -300.0)


def test_non_positive_factors_rejected() -> None:
    with pytest.raises(ValueError, match="vant_hoff_factor"):
        osmotic_pressure_bar(35000.0, 25.0, vant_hoff_factor=0.0)
    with pytest.raises(ValueError, match="molar_mass_g_per_mol"):
        osmotic_pressure_bar(35000.0, 25.0, molar_mass_g_per_mol=0.0)
