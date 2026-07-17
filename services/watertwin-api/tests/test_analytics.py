"""Tests for Phase 3 analytics: health scoring, physics-informed anomaly
detection, and cyber-physical consistency checks."""

from __future__ import annotations

import math

import pytest

from watertwin.analytics import (
    ANOMALY_WEIGHTS,
    AnomalyDomain,
    Baseline,
    HealthBand,
    PumpAsset,
    Telemetry,
    anomaly_score,
    cyber_physical_flags,
    pump_health_score,
)


@pytest.fixture
def asset() -> PumpAsset:
    return PumpAsset()


@pytest.fixture
def healthy_telemetry() -> Telemetry:
    return Telemetry(
        status="running",
        flow=100.0,
        vibration=1.8,
        bearing_temperature=45.0,
        efficiency=0.84,
        motor_power=15.2,
        motor_current=[28.0, 28.1, 27.9],
        seal_leakage=0.3,
        cavitation_index=0.02,
        suction_pressure=180.0,
        discharge_pressure=680.0,
        water_temperature=20.0,
        level_rate=0.0,
        sensor_uncertainty=0.02,
        days_since_maintenance=30.0,
    )


@pytest.fixture
def degraded_telemetry() -> Telemetry:
    return Telemetry(
        status="running",
        flow=55.0,
        vibration=9.5,  # above 7.1 limit
        bearing_temperature=98.0,  # above 90 limit
        efficiency=0.55,  # well below rated 0.85
        motor_power=18.0,
        motor_current=[26.0, 30.0, 34.0],  # imbalanced
        seal_leakage=6.5,  # above limit
        cavitation_index=0.38,  # above limit
        suction_pressure=150.0,
        discharge_pressure=520.0,
        water_temperature=25.0,
        sensor_uncertainty=0.4,
        days_since_maintenance=420.0,  # overdue
    )


# ---------------------------------------------------------------------------
# Health scoring
# ---------------------------------------------------------------------------
def test_healthy_input_scores_high(asset, healthy_telemetry):
    result = pump_health_score(asset, healthy_telemetry)
    assert result.score >= 90
    assert result.band == HealthBand.EXCELLENT
    assert result.score == max(0.0, min(100.0, result.score))


def test_degraded_input_scores_low_with_visible_breakdown(asset, degraded_telemetry):
    result = pump_health_score(asset, degraded_telemetry)
    assert result.score < 75
    # The breakdown must never be hidden.
    assert result.contributions, "degraded input must return contributions"
    # Every contribution must be a real (negative) penalty with a detail string.
    for c in result.contributions:
        assert c.delta < 0
        assert c.factor
        assert c.detail
    # Score must equal 100 plus the sum of penalties, clamped to [0, 100].
    expected = max(0.0, min(100.0, 100.0 + sum(c.delta for c in result.contributions)))
    assert result.score == pytest.approx(expected, abs=0.01)


def test_health_score_clamped_to_range(asset):
    catastrophic = Telemetry(
        status="running",
        flow=10.0,
        vibration=40.0,
        bearing_temperature=200.0,
        efficiency=0.1,
        motor_current=[10.0, 40.0, 80.0],
        seal_leakage=50.0,
        cavitation_index=1.0,
        sensor_uncertainty=1.0,
        days_since_maintenance=2000.0,
    )
    result = pump_health_score(asset, catastrophic)
    assert 0.0 <= result.score <= 100.0
    assert result.band == HealthBand.CRITICAL


def test_health_band_from_score_boundaries():
    assert HealthBand.from_score(100) == HealthBand.EXCELLENT
    assert HealthBand.from_score(90) == HealthBand.EXCELLENT
    assert HealthBand.from_score(89.9) == HealthBand.GOOD
    assert HealthBand.from_score(75) == HealthBand.GOOD
    assert HealthBand.from_score(50) == HealthBand.FAIR
    assert HealthBand.from_score(25) == HealthBand.POOR
    assert HealthBand.from_score(0) == HealthBand.CRITICAL


def test_contribution_factors_are_expected(asset, degraded_telemetry):
    result = pump_health_score(asset, degraded_telemetry)
    factors = {c.factor for c in result.contributions}
    for expected in ("vibration", "bearing_temperature", "current_imbalance",
                     "cavitation", "seal_leakage", "maintenance_age",
                     "sensor_uncertainty"):
        assert expected in factors


# ---------------------------------------------------------------------------
# Anomaly scoring
# ---------------------------------------------------------------------------
def test_anomaly_weights_sum_to_one():
    assert math.isclose(sum(ANOMALY_WEIGHTS.values()), 1.0, abs_tol=1e-9)


def test_anomaly_weight_names_and_values():
    assert ANOMALY_WEIGHTS == {
        "statistical_deviation": 0.25,
        "hydraulic_residual": 0.25,
        "pump_curve_deviation": 0.20,
        "cross_sensor_inconsistency": 0.15,
        "failure_pattern_similarity": 0.10,
        "operational_criticality": 0.05,
    }


def _baseline() -> Baseline:
    return Baseline(
        metrics={
            "flow": (100.0, 8.0),
            "vibration": (1.8, 0.5),
            "bearing_temperature": (45.0, 5.0),
            "motor_power": (15.0, 1.0),
        }
    )


def test_anomaly_score_bounded_healthy(asset, healthy_telemetry):
    result = anomaly_score(asset, healthy_telemetry, _baseline())
    assert 0.0 <= result.score <= 1.0
    for name, value in result.factors.items():
        assert name in ANOMALY_WEIGHTS
        assert 0.0 <= value <= 1.0


def test_anomaly_score_bounded_degraded(asset, degraded_telemetry):
    result = anomaly_score(asset, degraded_telemetry, _baseline())
    assert 0.0 <= result.score <= 1.0
    for value in result.factors.values():
        assert 0.0 <= value <= 1.0


def test_degraded_more_anomalous_than_healthy(asset, healthy_telemetry, degraded_telemetry):
    healthy = anomaly_score(asset, healthy_telemetry, _baseline())
    degraded = anomaly_score(asset, degraded_telemetry, _baseline())
    assert degraded.score > healthy.score


def test_anomaly_domains_ranked_by_contribution(asset):
    # Strong hydraulic residual: running with flow/head but implausible power.
    telemetry = Telemetry(
        status="running",
        flow=100.0,
        head=50.0,
        motor_power=0.5,  # far too low for this duty
        efficiency=0.8,
        vibration=1.8,
        bearing_temperature=45.0,
    )
    result = anomaly_score(asset, telemetry, _baseline())
    assert result.domains
    assert AnomalyDomain.HYDRAULIC in result.domains


def test_cross_sensor_maps_to_sensor_and_cyber_physical(asset):
    telemetry = Telemetry(status="running", flow=0.0, motor_power=12.0)
    result = anomaly_score(asset, telemetry, Baseline())
    assert AnomalyDomain.SENSOR in result.domains
    assert AnomalyDomain.CYBER_PHYSICAL in result.domains


# ---------------------------------------------------------------------------
# Cyber-physical flags
# ---------------------------------------------------------------------------
def test_running_no_flow_flag_fires():
    telemetry = Telemetry(status="running", flow=0.0, motor_power=0.0)
    assert "running_no_flow" in cyber_physical_flags(telemetry)


def test_running_no_flow_with_near_zero_flow():
    telemetry = Telemetry(status="running", flow=0.4, motor_power=0.0)
    assert "running_no_flow" in cyber_physical_flags(telemetry)


def test_power_without_flow_flag():
    telemetry = Telemetry(status="running", flow=0.0, motor_power=12.0)
    flags = cyber_physical_flags(telemetry)
    assert "power_without_flow" in flags
    assert "running_no_flow" in flags


def test_flow_without_power_flag():
    telemetry = Telemetry(status="running", flow=80.0, motor_power=0.0)
    assert "flow_without_power" in cyber_physical_flags(telemetry)


def test_suction_below_vapor_flag():
    # Vapor pressure of water at 20C is ~2.34 kPa.
    telemetry = Telemetry(
        status="running", flow=90.0, motor_power=14.0,
        suction_pressure=1.0, water_temperature=20.0,
    )
    assert "suction_below_vapor" in cyber_physical_flags(telemetry)


def test_suction_above_vapor_no_flag():
    telemetry = Telemetry(
        status="running", flow=90.0, motor_power=14.0,
        suction_pressure=120.0, water_temperature=20.0,
    )
    assert "suction_below_vapor" not in cyber_physical_flags(telemetry)


def test_level_change_without_flow_flag():
    telemetry = Telemetry(status="running", flow=0.0, motor_power=0.0, level_rate=0.05)
    assert "level_change_without_flow" in cyber_physical_flags(telemetry)


def test_healthy_telemetry_has_no_flags(healthy_telemetry):
    assert cyber_physical_flags(healthy_telemetry) == []
