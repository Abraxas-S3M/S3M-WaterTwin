"""Physical-plausibility tests for the baseline RO simulation."""

from __future__ import annotations

from app import ro_model

# Standard seawater feed: 35 g/L TDS, 25 C, 60 bar applied pressure.
SEAWATER = dict(
    feed_flow_m3h=100.0,
    feed_tds_mg_l=35000.0,
    feed_pressure_bar=60.0,
    membrane_area_m2=1200.0,
    temperature_c=25.0,
)


def test_baseline_recovery_in_plausible_range():
    res = ro_model.simulate_ro(**SEAWATER)
    # Single-stage SWRO recovery is typically ~0.35-0.55.
    assert 0.25 <= res.recovery <= 0.60


def test_baseline_specific_energy_in_plausible_range():
    res = ro_model.simulate_ro(**SEAWATER)
    # SWRO with energy recovery: ~1.8-4.5 kWh/m3.
    assert 1.5 <= res.specific_energy_kwh_m3 <= 5.0


def test_permeate_tds_below_feed():
    res = ro_model.simulate_ro(**SEAWATER)
    assert res.permeate_tds_mg_l < SEAWATER["feed_tds_mg_l"]
    # High-rejection SWRO permeate is well under the feed and near potable.
    assert res.permeate_tds_mg_l < 1000.0
    assert res.salt_rejection > 0.98


def test_mass_balance_closes():
    res = ro_model.simulate_ro(**SEAWATER)
    total = res.permeate_flow_m3h + res.concentrate_flow_m3h
    assert abs(total - SEAWATER["feed_flow_m3h"]) < 1e-6
    # Concentrate is more saline than the feed.
    assert res.concentrate_tds_mg_l > SEAWATER["feed_tds_mg_l"]


def test_provenance_and_status_labels():
    res = ro_model.simulate_ro(**SEAWATER)
    assert res.provenance.value == "simulated"
    assert res.status.value == "preliminary"
