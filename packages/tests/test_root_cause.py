"""Tests for the causal root-cause ranker.

The critical, decision-relevant invariant is the canonical HP-pump worked
example: with power +11% and production -6% plus elevated water-quality fouling
signals, the ranker must order the causes membrane fouling > pump-efficiency
loss > feed-salinity rise > valve restriction > sensor error, with each cause
carrying a distinct evidence string and the probabilities summing to ~1.0.
"""

from __future__ import annotations

import pytest

from watertwin_engineering import root_cause_rank


def _hpp_scenario():
    asset = {"asset_id": "AST-HPP-01", "asset_type": "hp_pump"}
    telemetry = {"power_pct_change": 11.0, "production_pct_change": -6.0}
    context = {
        "normalized_dp_rise_pct": 12.0,
        "normalized_salt_passage_rise_pct": 8.0,
        "pump_curve_efficiency_deviation_pct": 3.0,
        "feed_salinity_rise_pct": 2.0,
        "valve_position_error_pct": 1.0,
        "sensor_consistency": 0.95,
        "last_cip_days": 45.0,
        "days_since_pump_service": 220.0,
        "days_since_calibration": 90.0,
    }
    return asset, telemetry, context


def test_hpp_power_up_production_down_ranking_is_canonical() -> None:
    asset, telemetry, context = _hpp_scenario()
    ranked = root_cause_rank(asset, telemetry, context)

    order = [rc.cause for rc in ranked]
    assert order == [
        "membrane_fouling",
        "pump_efficiency_loss",
        "feed_salinity_rise",
        "valve_restriction",
        "sensor_error",
    ]


def test_ranking_probabilities_sum_to_one() -> None:
    asset, telemetry, context = _hpp_scenario()
    ranked = root_cause_rank(asset, telemetry, context)
    assert sum(rc.probability for rc in ranked) == pytest.approx(1.0, abs=1e-3)


def test_each_cause_carries_distinct_evidence() -> None:
    asset, telemetry, context = _hpp_scenario()
    ranked = root_cause_rank(asset, telemetry, context)
    evidences = [rc.evidence for rc in ranked]
    assert all(e for e in evidences)
    assert len(set(evidences)) == len(evidences)
    by_cause = {rc.cause: rc.evidence for rc in ranked}
    # Evidence types: WQ signal, curve deviation, sensor value, sensor value,
    # historical comparison.
    assert "WQ signal" in by_cause["membrane_fouling"]
    assert "Curve deviation" in by_cause["pump_efficiency_loss"]
    assert "Historical comparison" in by_cause["sensor_error"]


def test_top_cause_is_membrane_fouling_and_dominant() -> None:
    asset, telemetry, context = _hpp_scenario()
    ranked = root_cause_rank(asset, telemetry, context)
    assert ranked[0].cause == "membrane_fouling"
    assert ranked[0].probability > ranked[1].probability


def test_sensor_error_dominates_when_signals_inconsistent() -> None:
    asset = {"asset_id": "AST-HPP-01"}
    telemetry = {"power_pct_change": 0.0, "production_pct_change": 0.0}
    context = {"sensor_consistency": 0.2}
    ranked = root_cause_rank(asset, telemetry, context)
    assert ranked[0].cause == "sensor_error"


def test_missing_telemetry_mapping_raises() -> None:
    with pytest.raises(ValueError):
        root_cause_rank({"asset_id": "x"}, telemetry=None)  # type: ignore[arg-type]
