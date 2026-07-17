"""Tests for the deterministic equipment / predictive-maintenance physics.

These lock the decision-relevant invariants: component health is a transparent
visible-penalty score (a degraded component scores lower and every deduction is
explained), RUL is preliminary with an uncertainty band and shortens as
degradation accelerates, failure probability is monotonic in every input, the
operating-envelope fractions are well-formed, and maintenance priority rises
with risk and falls with redundancy/spares.
"""

from __future__ import annotations

import pytest

from watertwin_engineering import (
    component_health,
    failure_probability,
    maintenance_priority,
    operating_envelope_score,
    remaining_useful_life_days,
)
from watertwin_engineering.equipment import COMPONENT_TYPES


# --- component_health -------------------------------------------------------


def test_healthy_motor_scores_full_with_no_penalties() -> None:
    result = component_health(
        "motor",
        {
            "current_imbalance_pct": 0.0,
            "voltage_imbalance_pct": 0.0,
            "winding_temp_c": 90.0,
            "winding_temp_limit_c": 155.0,
            "vibration_mm_s": 2.0,
            "vibration_limit_mm_s": 4.5,
        },
    )
    assert result.score == 100.0
    assert result.band == "Healthy"
    assert result.contributions == []
    assert result.provenance == "preliminary"


def test_degraded_motor_scores_lower_with_visible_contributions() -> None:
    healthy = component_health(
        "motor",
        {"current_imbalance_pct": 0.0, "winding_temp_c": 90.0, "vibration_mm_s": 2.0},
    )
    degraded = component_health(
        "motor",
        {
            "current_imbalance_pct": 6.0,
            "voltage_imbalance_pct": 3.0,
            "winding_temp_c": 165.0,
            "winding_temp_limit_c": 155.0,
            "vibration_mm_s": 7.5,
            "vibration_limit_mm_s": 4.5,
        },
    )
    assert degraded.score < healthy.score
    # Every deduction is a visible, labelled contribution with a negative delta.
    assert degraded.contributions
    factors = {c.factor for c in degraded.contributions}
    assert {"Current imbalance", "Voltage imbalance", "Winding temperature", "Vibration"} <= factors
    assert all(c.delta < 0 for c in degraded.contributions)
    assert all(c.detail for c in degraded.contributions)
    # Score reconciles with the sum of the visible penalties.
    expected = max(0.0, 100.0 + sum(c.delta for c in degraded.contributions))
    assert degraded.score == pytest.approx(round(expected, 1), abs=0.1)


@pytest.mark.parametrize("component_type", COMPONENT_TYPES)
def test_every_component_type_scores_within_bounds(component_type: str) -> None:
    result = component_health(component_type, {})
    assert 0.0 <= result.score <= 100.0
    # With empty telemetry (all-nominal) no penalties apply.
    assert result.score == 100.0


def test_filter_normalized_dp_penalizes_health() -> None:
    clean = component_health("filter", {"normalized_dp": 1.0})
    fouled = component_health("filter", {"normalized_dp": 2.5})
    assert fouled.score < clean.score
    assert any("Differential pressure" == c.factor for c in fouled.contributions)


def test_erd_efficiency_loss_penalizes_health() -> None:
    good = component_health("erd", {"transfer_efficiency_pct": 96.0})
    poor = component_health(
        "erd", {"transfer_efficiency_pct": 88.0, "rated_transfer_efficiency_pct": 96.0}
    )
    assert poor.score < good.score


def test_unknown_component_type_raises() -> None:
    with pytest.raises(ValueError):
        component_health("turbine", {})


# --- operating_envelope_score ----------------------------------------------


def test_operating_envelope_fractions_are_wellformed() -> None:
    history = [
        {"flow_m3h": 500, "bep_flow_m3h": 500, "pressure_bar": 60, "max_pressure_bar": 70,
         "temperature_c": 30, "temp_limit_c": 45},
        {"flow_m3h": 300, "bep_flow_m3h": 500, "pressure_bar": 75, "max_pressure_bar": 70,
         "temperature_c": 50, "temp_limit_c": 45, "npsh_available_m": 3.0, "npsh_required_m": 3.2},
    ]
    env = operating_envelope_score(history)
    assert env.samples == 2
    for frac in (
        env.at_bep_fraction,
        env.low_flow_fraction,
        env.high_pressure_fraction,
        env.excess_temperature_fraction,
        env.cavitation_risk_fraction,
    ):
        assert 0.0 <= frac <= 1.0
    assert env.at_bep_fraction == 0.5  # first sample at BEP
    assert env.low_flow_fraction == 0.5  # second sample below 70% of BEP
    assert env.high_pressure_fraction == 0.5
    assert env.excess_temperature_fraction == 0.5
    assert env.cavitation_risk_fraction == 0.5
    assert env.provenance == "preliminary"


def test_operating_envelope_empty_history_raises() -> None:
    with pytest.raises(ValueError):
        operating_envelope_score([])


# --- remaining_useful_life_days --------------------------------------------


def test_rul_returns_band_and_preliminary_provenance() -> None:
    rul = remaining_useful_life_days(
        health_trend=[90, 88, 86, 84, 82],
        duty_cycle=0.5,
        maintenance_age_days=100,
        recommended_interval_days=365,
        comparable_asset_factor=1.0,
    )
    assert rul.provenance == "preliminary"
    assert rul.lower_days <= rul.rul_days <= rul.upper_days
    assert rul.lower_days >= 0.0
    assert rul.basis  # documented method basis is exposed


def test_rul_shorter_for_faster_degradation() -> None:
    slow = remaining_useful_life_days(
        health_trend=[90, 89, 88, 87, 86],
        duty_cycle=0.5,
        maintenance_age_days=100,
        recommended_interval_days=365,
    )
    fast = remaining_useful_life_days(
        health_trend=[90, 84, 78, 72, 66],
        duty_cycle=0.5,
        maintenance_age_days=100,
        recommended_interval_days=365,
    )
    assert fast.rul_days < slow.rul_days


def test_rul_shorter_for_higher_duty_and_overdue_maintenance() -> None:
    trend = [90, 86, 82, 78, 74]
    light = remaining_useful_life_days(trend, 0.2, 50, 365)
    heavy = remaining_useful_life_days(trend, 0.95, 400, 365)
    assert heavy.rul_days < light.rul_days


# --- failure_probability ----------------------------------------------------


def test_failure_probability_horizons_present_and_bounded() -> None:
    fp = failure_probability("Degraded", anomaly_score=0.5, rul_days=60)
    assert set(fp.horizons) == {"24h", "7d", "30d", "90d"}
    assert all(0.0 <= p <= 1.0 for p in fp.horizons.values())
    # Longer horizons are at least as likely as shorter ones.
    assert fp.horizons["24h"] <= fp.horizons["7d"] <= fp.horizons["30d"] <= fp.horizons["90d"]
    assert fp.provenance == "preliminary"


def test_failure_probability_monotonic_in_health_band() -> None:
    bands = ["Healthy", "Monitor", "Degraded", "HighRisk", "Critical"]
    p30 = [failure_probability(b, 0.3, 60).horizons["30d"] for b in bands]
    assert p30 == sorted(p30)


def test_failure_probability_monotonic_in_anomaly_and_rul() -> None:
    low_anom = failure_probability("Degraded", 0.1, 60).horizons["30d"]
    high_anom = failure_probability("Degraded", 0.9, 60).horizons["30d"]
    assert high_anom > low_anom

    long_rul = failure_probability("Degraded", 0.3, 300).horizons["30d"]
    short_rul = failure_probability("Degraded", 0.3, 5).horizons["30d"]
    assert short_rul > long_rul


# --- maintenance_priority ---------------------------------------------------


def test_maintenance_priority_rises_with_risk() -> None:
    low = maintenance_priority(0.1, 0.3, 0.2, redundancy=1, spares_available=True)
    high = maintenance_priority(0.8, 0.9, 0.9, redundancy=0, spares_available=False)
    assert high.rank_score > low.rank_score


def test_maintenance_priority_redundancy_and_spares_reduce_urgency() -> None:
    base = maintenance_priority(0.6, 0.7, 0.6, redundancy=0, spares_available=False)
    redundant = maintenance_priority(0.6, 0.7, 0.6, redundancy=2, spares_available=False)
    with_spares = maintenance_priority(0.6, 0.7, 0.6, redundancy=0, spares_available=True)
    assert redundant.rank_score < base.rank_score
    assert with_spares.rank_score < base.rank_score


def test_maintenance_priority_safety_weight_elevates() -> None:
    normal = maintenance_priority(0.5, 0.5, 0.5, redundancy=0, spares_available=True)
    safety = maintenance_priority(
        0.5, 0.5, 0.5, redundancy=0, spares_available=True, safety_or_wq_weight=2.0
    )
    assert safety.rank_score > normal.rank_score
