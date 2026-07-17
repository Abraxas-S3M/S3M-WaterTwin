"""Tests for the lumped analytical RO reference (``calculations``).

These lock the critical physics assertions the platform depends on and confirm
the lumped reference reuses the single canonical osmotic-pressure function.
"""

from __future__ import annotations

import pytest

from watertwin_engineering import calculations
from watertwin_engineering.calculations import ROReference, osmotic_pressure_bar, ro_performance


def test_seawater_osmotic_pressure_in_expected_band() -> None:
    # Critical invariant: 35 g/L seawater at 25 C is ~24-30 bar (van 't Hoff).
    assert 24.0 < osmotic_pressure_bar(35000.0, 25.0) < 30.0


def test_calculations_reuses_single_osmotic_implementation() -> None:
    from watertwin_engineering.osmotic import osmotic_pressure_bar as canonical

    assert calculations.osmotic_pressure_bar is canonical


def test_ro_performance_seawater_reference_is_plausible() -> None:
    ref = ro_performance(
        feed_flow_m3h=100.0,
        feed_tds_mg_l=35000.0,
        feed_pressure_bar=60.0,
        membrane_area_m2=1200.0,
    )
    assert isinstance(ref, ROReference)
    assert 0.25 <= ref.recovery <= 0.60
    assert ref.permeate_tds_mg_l < 35000.0
    assert ref.salt_rejection > 0.9
    assert 1.5 <= ref.specific_energy_kwh_m3 <= 5.0


def test_ro_performance_mass_balance_closes() -> None:
    ref = ro_performance(
        feed_flow_m3h=100.0,
        feed_tds_mg_l=35000.0,
        feed_pressure_bar=60.0,
        membrane_area_m2=1200.0,
    )
    total = ref.permeate_flow_m3h + ref.concentrate_flow_m3h
    assert total == pytest.approx(100.0, rel=1e-6)


def test_specific_energy_with_erd_is_lower() -> None:
    without = calculations.specific_energy(100.0, 60.0, 0.45, use_erd=False)
    with_erd = calculations.specific_energy(100.0, 60.0, 0.45, use_erd=True)
    assert with_erd < without
