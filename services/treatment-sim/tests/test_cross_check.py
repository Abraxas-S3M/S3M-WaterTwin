"""Cross-check the service RO model against the analytical reference.

The two are independent implementations of the same physics (discretized
multi-segment vs lumped average element). They must agree within tolerance for a
range of seawater/brackish conditions; a larger divergence is a bug signal.
"""

from __future__ import annotations

import pytest

from app import ro_model
from watertwin_engineering import calculations

TOLERANCE = 0.15

CASES = [
    dict(feed_flow_m3h=100.0, feed_tds_mg_l=35000.0, feed_pressure_bar=60.0, membrane_area_m2=1200.0),
    dict(feed_flow_m3h=120.0, feed_tds_mg_l=38000.0, feed_pressure_bar=65.0, membrane_area_m2=1400.0),
    dict(feed_flow_m3h=80.0, feed_tds_mg_l=32000.0, feed_pressure_bar=55.0, membrane_area_m2=1000.0),
    dict(feed_flow_m3h=100.0, feed_tds_mg_l=5000.0, feed_pressure_bar=20.0, membrane_area_m2=1000.0),
]


def _rel(a: float, b: float) -> float:
    return abs(a - b) / b if b else abs(a - b)


@pytest.mark.parametrize("case", CASES)
def test_recovery_agrees(case):
    sim = ro_model.simulate_ro(**case)
    ref = calculations.ro_performance(**case)
    assert _rel(sim.recovery, ref.recovery) <= TOLERANCE


@pytest.mark.parametrize("case", CASES)
def test_specific_energy_agrees(case):
    sim = ro_model.simulate_ro(**case)
    ref = calculations.ro_performance(**case)
    assert _rel(sim.specific_energy_kwh_m3, ref.specific_energy_kwh_m3) <= TOLERANCE


@pytest.mark.parametrize("case", CASES)
def test_permeate_tds_agrees(case):
    sim = ro_model.simulate_ro(**case)
    ref = calculations.ro_performance(**case)
    # Permeate TDS is small; compare with a looser absolute + relative bound.
    assert _rel(sim.permeate_tds_mg_l, ref.permeate_tds_mg_l) <= 0.35
