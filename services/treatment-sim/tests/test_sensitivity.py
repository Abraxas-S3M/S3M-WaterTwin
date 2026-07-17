"""Sensitivity monotonicity tests.

Higher feed salinity must raise specific energy and/or degrade permeate quality;
these are fundamental RO responses and a violation signals a physics bug.
"""

from __future__ import annotations

from app import engine
from simulation_contracts import (
    ROFeed,
    ROMembrane,
    SensitivityRequest,
    SensitivitySweep,
)


def _request(sweep: SensitivitySweep) -> SensitivityRequest:
    return SensitivityRequest(
        feed=ROFeed(flow_m3h=100.0, tds_mg_l=35000.0, temperature_c=25.0, pressure_bar=60.0),
        membrane=ROMembrane(area_m2=1200.0),
        sweep=sweep,
    )


def test_higher_salinity_raises_energy_or_lowers_quality():
    sweep = SensitivitySweep(
        variable="feed_tds_mg_l", start=30000.0, stop=45000.0, steps=6
    )
    result = engine.run_sensitivity(_request(sweep))
    points = result.points
    assert len(points) == 6

    first, last = points[0].result, points[-1].result
    # Either specific energy rises OR permeate quality worsens (higher TDS).
    energy_rises = last.specific_energy_kwh_m3 >= first.specific_energy_kwh_m3
    quality_worsens = last.permeate_tds_mg_l >= first.permeate_tds_mg_l
    assert energy_rises or quality_worsens

    # Recovery must not increase as salinity rises (osmotic pressure grows).
    recoveries = [p.result.recovery for p in points]
    assert recoveries[-1] <= recoveries[0] + 1e-6


def test_permeate_tds_monotonic_in_salinity():
    sweep = SensitivitySweep(
        variable="feed_tds_mg_l", start=30000.0, stop=45000.0, steps=6
    )
    result = engine.run_sensitivity(_request(sweep))
    tds = [p.result.permeate_tds_mg_l for p in result.points]
    for a, b in zip(tds, tds[1:]):
        assert b >= a - 1e-6


def test_higher_pressure_increases_recovery():
    sweep = SensitivitySweep(
        variable="feed_pressure_bar", start=50.0, stop=70.0, steps=5
    )
    result = engine.run_sensitivity(_request(sweep))
    recoveries = [p.result.recovery for p in result.points]
    for a, b in zip(recoveries, recoveries[1:]):
        assert b >= a - 1e-6
