"""Tests for the whole-train RO evaluation."""

from __future__ import annotations

import pytest

from watertwin.engineering.train import TrainEvaluation, evaluate_train


def _nominal_kwargs() -> dict[str, float]:
    return {
        "feed_pressure_bar": 60.0,
        "permeate_pressure_bar": 0.5,
        "feed_flow_m3_per_h": 100.0,
        "permeate_flow_m3_per_h": 45.0,
        "feed_tds_mg_per_l": 35000.0,
        "permeate_tds_mg_per_l": 350.0,
        "temperature_c": 25.0,
        "membrane_permeability_lmh_per_bar": 1.0,
        "feed_channel_dp_bar": 2.0,
        "pump_efficiency": 0.8,
        "energy_recovery_efficiency": 0.0,
    }


def test_evaluate_train_returns_evaluation() -> None:
    result = evaluate_train(**_nominal_kwargs())
    assert isinstance(result, TrainEvaluation)


def test_evaluate_train_core_metrics() -> None:
    result = evaluate_train(**_nominal_kwargs())
    assert result.recovery_fraction == pytest.approx(0.45, rel=1e-9)
    assert result.salt_rejection_fraction == pytest.approx(0.99, rel=1e-9)
    assert result.salt_passage_fraction == pytest.approx(0.01, rel=1e-9)
    assert result.concentration_factor == pytest.approx(0.9955 / 0.55, rel=1e-9)


def test_evaluate_train_concentrate_osmotic_exceeds_feed() -> None:
    result = evaluate_train(**_nominal_kwargs())
    assert result.concentrate_osmotic_pressure_bar > result.feed_osmotic_pressure_bar
    assert (
        result.feed_osmotic_pressure_bar
        < result.average_feed_side_osmotic_pressure_bar
        < result.concentrate_osmotic_pressure_bar
    )


def test_evaluate_train_flux_positive_and_finite() -> None:
    result = evaluate_train(**_nominal_kwargs())
    assert result.water_flux_lmh > 0
    assert result.net_driving_pressure_bar > 0


def test_evaluate_train_tcf_unity_at_reference() -> None:
    result = evaluate_train(**_nominal_kwargs())
    assert result.temperature_correction_factor == pytest.approx(1.0, rel=1e-12)
    assert result.normalized_permeate_flow_m3_per_h == pytest.approx(45.0, rel=1e-9)


def test_evaluate_train_sec_reasonable() -> None:
    result = evaluate_train(**_nominal_kwargs())
    assert result.specific_energy_consumption_kwh_per_m3 == pytest.approx(4.6296, rel=1e-3)


def test_evaluate_train_is_deterministic() -> None:
    first = evaluate_train(**_nominal_kwargs())
    second = evaluate_train(**_nominal_kwargs())
    assert first == second


def test_evaluate_train_propagates_validation_errors() -> None:
    kwargs = _nominal_kwargs()
    kwargs["permeate_flow_m3_per_h"] = 200.0  # recovery > 1
    with pytest.raises(ValueError, match="recovery > 1"):
        evaluate_train(**kwargs)
