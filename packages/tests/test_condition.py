"""Tests for the condition-intelligence framework.

These lock the decision-relevant invariants of the framework itself (not any one
model):

* the :class:`ModelSpec` contract rejects an incomplete model;
* the back-test computes precision / recall / false-alarm rate / lead time
  correctly on a fixture with hand-checked labels;
* the drift monitor's flag fires on a shifted distribution and stays clear on an
  unshifted one; and
* every output carries an uncertainty bound and a ``provenance`` stamp.
"""

from __future__ import annotations

import pytest

from watertwin_engineering.condition import (
    FeatureSpec,
    ModelSpec,
    ThresholdConditionModel,
    UncertaintyMethod,
    ValidRange,
    calibrate,
    monitor_drift,
    run_backtest,
)


def _spec(model_id: str = "test-threshold") -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        version="1.0.0",
        description="A single-feature threshold reference model for tests.",
        equation_source="linear ramp on feature x (test fixture)",
        feature_spec=(FeatureSpec(name="x", unit="dimensionless"),),
        assumptions=("x is a normalized, sensor-validated signal.",),
        valid_range=ValidRange({"x": (0.0, 100.0)}),
        uncertainty_method=UncertaintyMethod(
            name="residual-sigma", description="feature sigma through the slope."
        ),
        failure_modes=("sensor drift read as degradation.",),
        explainability_outputs=("per-feature contribution",),
    )


def _model(alarm_at: float = 10.0, sigma: float = 0.0) -> ThresholdConditionModel:
    # severity = x / alarm_at; alarm when severity >= 0.5 -> x >= alarm_at/2.
    return ThresholdConditionModel(
        spec=_spec(),
        feature="x",
        warn_at=0.0,
        alarm_at=alarm_at,
        feature_sigma=sigma,
        alarm_score_threshold=0.5,
    )


# --- ModelSpec contract -----------------------------------------------------


def test_valid_spec_passes_validation() -> None:
    _spec().validate()  # does not raise


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: {**s, "equation_source": ""},
        lambda s: {**s, "feature_spec": ()},
        lambda s: {**s, "assumptions": ()},
        lambda s: {**s, "failure_modes": ()},
        lambda s: {**s, "explainability_outputs": ()},
        lambda s: {**s, "version": "  "},
    ],
)
def test_incomplete_spec_is_rejected(mutate) -> None:
    base = _spec()
    kwargs = {
        "model_id": base.model_id,
        "version": base.version,
        "description": base.description,
        "equation_source": base.equation_source,
        "feature_spec": base.feature_spec,
        "assumptions": base.assumptions,
        "valid_range": base.valid_range,
        "uncertainty_method": base.uncertainty_method,
        "failure_modes": base.failure_modes,
        "explainability_outputs": base.explainability_outputs,
    }
    spec = ModelSpec(**mutate(kwargs))
    with pytest.raises(ValueError):
        spec.validate()


def test_valid_range_flags_extrapolation() -> None:
    model = _model()
    inside = model.score({"x": 5.0})
    outside = model.score({"x": 500.0})
    assert inside.in_valid_range is True
    assert outside.in_valid_range is False
    assert outside.range_violations


# --- ConditionScore: uncertainty bounds + provenance ------------------------


def test_score_carries_bounds_and_provenance() -> None:
    result = _model(sigma=1.0).score({"x": 5.0})
    assert result.provenance == "preliminary"
    assert 0.0 <= result.lower <= result.score <= result.upper <= 1.0
    # A non-zero feature sigma must widen the band beyond a point estimate.
    assert result.upper > result.lower
    assert result.contributions and result.contributions[0].feature == "x"


# --- Back-test metrics on a hand-checked fixture ----------------------------


def _known_history() -> list[dict]:
    # alarm fires when x >= 5 (alarm_at=10, threshold 0.5). Labels are chosen so
    # the confusion matrix is: TP=2, FP=1, TN=2, FN=1, with one event onset that
    # is alarmed one step early (lead time = 1).
    return [
        {"t": 0, "features": {"x": 1.0}, "label": False},  # TN
        {"t": 1, "features": {"x": 2.0}, "label": False},  # TN
        {"t": 2, "features": {"x": 6.0}, "label": False},  # FP (early warning)
        {"t": 3, "features": {"x": 7.0}, "label": True},   # TP (onset)
        {"t": 4, "features": {"x": 8.0}, "label": True},   # TP
        {"t": 5, "features": {"x": 3.0}, "label": True},   # FN (missed)
    ]


def test_backtest_metrics_are_correct_on_known_labels() -> None:
    result = run_backtest(_model(), _known_history())
    m = result.metrics
    confusion = (m.true_positives, m.false_positives, m.true_negatives, m.false_negatives)
    assert confusion == (2, 1, 2, 1)
    assert m.precision == pytest.approx(2 / 3, abs=1e-4)
    assert m.recall == pytest.approx(2 / 3, abs=1e-4)
    assert m.false_alarm_rate == pytest.approx(1 / 3, abs=1e-4)
    assert m.f1 == pytest.approx(2 / 3, abs=1e-4)
    assert result.provenance == "preliminary"


def test_backtest_lead_time_and_event_detection() -> None:
    result = run_backtest(_model(), _known_history())
    m = result.metrics
    assert m.events_total == 1
    assert m.events_detected == 1
    # The single onset at t=3 was alarmed at t=2 -> one time-unit of lead.
    assert m.mean_lead_time == pytest.approx(1.0, abs=1e-9)


def test_backtest_metrics_carry_confidence_intervals() -> None:
    m = run_backtest(_model(), _known_history()).metrics
    lo, hi = m.precision_ci
    assert 0.0 <= lo <= m.precision <= hi <= 1.0
    lo_r, hi_r = m.recall_ci
    assert 0.0 <= lo_r <= m.recall <= hi_r <= 1.0


def test_backtest_rejects_invalid_spec() -> None:
    bad = ThresholdConditionModel(
        spec=ModelSpec(
            model_id="bad",
            version="1",
            description="d",
            equation_source="",  # missing -> invalid
            feature_spec=(FeatureSpec("x", "u"),),
            assumptions=("a",),
            valid_range=ValidRange({"x": (0.0, 1.0)}),
            uncertainty_method=UncertaintyMethod("m", "d"),
            failure_modes=("f",),
            explainability_outputs=("e",),
        ),
        feature="x",
        warn_at=0.0,
        alarm_at=1.0,
    )
    with pytest.raises(ValueError):
        run_backtest(bad, _known_history())


def test_backtest_empty_history_raises() -> None:
    with pytest.raises(ValueError):
        run_backtest(_model(), [])


# --- Drift monitor ----------------------------------------------------------


def _baseline_window() -> list[dict]:
    return [{"features": {"x": i * 0.1}} for i in range(50)]  # 0.0 .. 4.9


def test_drift_flag_fires_on_shifted_distribution() -> None:
    baseline = _baseline_window()
    # Shift the live window well above the baseline's entire support.
    live = [{"features": {"x": i * 0.1 + 5.0}} for i in range(50)]
    result = monitor_drift(baseline, live, feature_names=["x"])
    assert result.drift_flag is True
    assert "x" in result.drifted_features
    assert result.max_psi >= result.psi_threshold
    fd = next(f for f in result.features if f.feature == "x")
    assert fd.mean_shift == pytest.approx(5.0, abs=1e-6)
    assert result.provenance == "preliminary"


def test_drift_flag_clear_on_unshifted_distribution() -> None:
    baseline = _baseline_window()
    live = _baseline_window()  # identical distribution
    result = monitor_drift(baseline, live, feature_names=["x"])
    assert result.drift_flag is False
    assert result.max_psi < result.psi_threshold


def test_drift_monitors_score_distribution_when_model_given() -> None:
    baseline = _baseline_window()
    live = [{"features": {"x": i * 0.1 + 5.0}} for i in range(50)]
    result = monitor_drift(baseline, live, model=_model())
    # With a model, the score pseudo-feature is monitored too.
    monitored = {f.feature for f in result.features}
    assert "__score__" in monitored
    assert result.drift_flag is True


def test_drift_empty_window_raises() -> None:
    with pytest.raises(ValueError):
        monitor_drift([], [{"features": {"x": 1.0}}], feature_names=["x"])


# --- Calibration ------------------------------------------------------------


def test_calibration_perfect_scores_have_zero_error() -> None:
    result = calibrate([0.0, 0.0, 1.0, 1.0], [False, False, True, True], n_bins=10)
    assert result.ece == pytest.approx(0.0, abs=1e-9)
    assert result.mce == pytest.approx(0.0, abs=1e-9)
    assert result.brier == pytest.approx(0.0, abs=1e-9)
    assert result.calibrated_confidence(1.0) == pytest.approx(1.0)
    assert result.calibrated_confidence(0.0) == pytest.approx(0.0)


def test_calibration_detects_overconfidence() -> None:
    # Model says 0.9 twice but both outcomes are negative -> badly calibrated.
    result = calibrate([0.9, 0.9], [False, False], n_bins=10)
    assert result.ece == pytest.approx(0.9, abs=1e-9)
    assert result.brier == pytest.approx(0.81, abs=1e-9)
    assert result.provenance == "preliminary"


def test_calibration_input_validation() -> None:
    with pytest.raises(ValueError):
        calibrate([0.1], [True, False])
    with pytest.raises(ValueError):
        calibrate([], [])
