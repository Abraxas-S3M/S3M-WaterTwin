"""Tests for the telemetry and analytics Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from watertwin.models.analytics import DISCLAIMER, TrainAnalytics, build_train_analytics
from watertwin.models.telemetry import TrainTelemetry


def _telemetry(**overrides: object) -> TrainTelemetry:
    base: dict[str, object] = {
        "feed_pressure_bar": 60.0,
        "permeate_pressure_bar": 0.5,
        "feed_channel_dp_bar": 2.0,
        "feed_flow_m3_per_h": 100.0,
        "permeate_flow_m3_per_h": 45.0,
        "feed_tds_mg_per_l": 35000.0,
        "permeate_tds_mg_per_l": 350.0,
        "temperature_c": 25.0,
    }
    base.update(overrides)
    return TrainTelemetry(**base)  # type: ignore[arg-type]


def test_telemetry_defaults_to_synthetic() -> None:
    telemetry = _telemetry()
    assert telemetry.provenance == "synthetic"


def test_telemetry_rejects_non_synthetic_provenance() -> None:
    with pytest.raises(ValidationError):
        _telemetry(provenance="measured")


def test_telemetry_rejects_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        _telemetry(feed_pressure_bar=0.0)
    with pytest.raises(ValidationError):
        _telemetry(pump_efficiency=1.5)


def test_telemetry_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _telemetry(command_valve="open")


def test_analytics_is_always_preliminary_with_disclaimer() -> None:
    analytics = build_train_analytics(_telemetry())
    assert analytics.status == "preliminary"
    assert analytics.disclaimer == DISCLAIMER
    assert "not a validated production prediction" in analytics.disclaimer.lower()


def test_analytics_carries_advisory_safety_envelope() -> None:
    analytics = build_train_analytics(_telemetry())
    assert analytics.safety.control_mode == "advisory"
    assert analytics.safety.control_write_enabled is False
    assert analytics.safety.operator_approval_required is True


def test_analytics_values_match_engine() -> None:
    analytics = build_train_analytics(_telemetry())
    assert analytics.recovery_fraction == pytest.approx(0.45, rel=1e-9)
    assert analytics.salt_rejection_fraction == pytest.approx(0.99, rel=1e-9)
    assert analytics.specific_energy_consumption_kwh_per_m3 == pytest.approx(4.6296, rel=1e-3)


def test_analytics_status_cannot_be_overridden() -> None:
    with pytest.raises(ValidationError):
        TrainAnalytics(
            train_id="train-1",
            status="validated",  # type: ignore[arg-type]
            recovery_fraction=0.45,
            salt_rejection_fraction=0.99,
            salt_passage_fraction=0.01,
            concentration_factor=1.8,
            feed_osmotic_pressure_bar=29.7,
            concentrate_osmotic_pressure_bar=40.0,
            average_feed_side_osmotic_pressure_bar=35.0,
            permeate_osmotic_pressure_bar=0.3,
            net_driving_pressure_bar=24.0,
            water_flux_lmh=24.0,
            temperature_correction_factor=1.0,
            normalized_permeate_flow_m3_per_h=45.0,
            specific_energy_consumption_kwh_per_m3=4.63,
        )
