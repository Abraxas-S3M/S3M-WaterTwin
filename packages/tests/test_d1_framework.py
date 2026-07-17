"""Tests for the D1 model framework (``watertwin_models``).

These lock the framework invariants: a :class:`ModelSpec` is D1-tier, read-only
and carries preliminary/pending-calibration thresholds; the back-test harness
returns a correct confusion matrix, false-alarm rate and lead time; the
false-alarm tracker accounts for operator dispositions over a window; the
calibration layer measures and (once fitted) recalibrates confidence; the drift
hook scores PSI against a baseline; and the benchmark scaffold aggregates the
above with a mandatory honesty disclaimer.
"""

from __future__ import annotations

import pytest

from watertwin_models import (
    AlertThreshold,
    BackTestDataset,
    BaselineRef,
    BenchmarkResult,
    ConfidenceCalibrator,
    FalseAlarmTracker,
    FeatureDriftMonitor,
    LabeledSample,
    ModelSpec,
    ModelTier,
    ThresholdDirection,
    brier_score,
    population_stability_index,
    reliability_curve,
    run_backtest,
    run_benchmark,
)


def _spec() -> ModelSpec:
    return ModelSpec(
        model_id="d1-test",
        version="0.1.0-preliminary",
        name="Test D1 model",
        description="A test model.",
        asset_type="pump",
        target="score",
        baseline=BaselineRef(name="b", description="d", source="synthetic"),
        thresholds=[
            AlertThreshold(
                name="High metric",
                metric="m",
                direction=ThresholdDirection.above,
                value=1.0,
                severity="warning",
                rationale="preliminary",
            )
        ],
    )


# --- ModelSpec --------------------------------------------------------------


def test_model_spec_is_d1_readonly_and_preliminary() -> None:
    spec = _spec()
    assert spec.tier == ModelTier.D1
    assert spec.provenance.value == "preliminary"
    assert spec.control_boundary.control_write_enabled is False
    assert spec.control_boundary.operator_approval_required is True
    # Every threshold is preliminary pending customer calibration.
    assert spec.thresholds
    for th in spec.thresholds:
        assert th.preliminary is True
        assert th.pending_customer_calibration is True
    # Configs default to pending calibration too.
    assert spec.drift.pending_customer_calibration is True
    assert spec.calibration.calibrated is False
    assert spec.false_alarm.pending_customer_calibration is True


def test_model_spec_round_trips_to_json() -> None:
    spec = _spec()
    dumped = spec.model_dump(mode="json")
    assert dumped["model_id"] == "d1-test"
    assert dumped["tier"] == "D1"


# --- back-test harness ------------------------------------------------------


def _dataset() -> BackTestDataset:
    return BackTestDataset(
        model_id="d1-test",
        name="ds",
        description="d",
        samples=[
            LabeledSample({"x": 0.9}, label=True, lead_time_days=10.0),
            LabeledSample({"x": 0.8}, label=True, lead_time_days=6.0),
            LabeledSample({"x": 0.2}, label=True),  # a miss (FN)
            LabeledSample({"x": 0.1}, label=False),
            LabeledSample({"x": 0.0}, label=False),
            LabeledSample({"x": 0.6}, label=False),  # a false alarm (FP)
        ],
    )


def test_run_backtest_confusion_and_rates() -> None:
    metrics = run_backtest(_dataset(), lambda f: f["x"], threshold=0.5)
    assert metrics.true_positives == 2
    assert metrics.false_negatives == 1
    assert metrics.false_positives == 1
    assert metrics.true_negatives == 2
    assert metrics.precision == pytest.approx(2 / 3, abs=1e-3)
    assert metrics.recall == pytest.approx(2 / 3, abs=1e-3)
    # false-alarm rate = FP / (FP + TN) = 1/3.
    assert metrics.false_alarm_rate == pytest.approx(1 / 3, abs=1e-3)
    # lead time averages only the detected positives (10, 6).
    assert metrics.mean_lead_time_days == pytest.approx(8.0, abs=1e-6)
    assert metrics.pending_customer_calibration is True


def test_run_backtest_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        run_backtest(
            BackTestDataset(model_id="x", name="n", description="d", samples=[]),
            lambda f: 0.0,
        )
    with pytest.raises(ValueError):
        run_backtest(_dataset(), lambda f: 0.0, threshold=1.5)


# --- false-alarm tracker ----------------------------------------------------


def test_false_alarm_tracker_rate_and_target() -> None:
    tracker = FalseAlarmTracker("d1-test", window=10, target_false_alarm_rate=0.5)
    tracker.record("a1", True)
    tracker.record("a2", False)
    tracker.record("a3", None)  # pending
    tracker.resolve("a3", False)
    summary = tracker.summary()
    assert summary.alerts_in_window == 3
    assert summary.true_alerts == 1
    assert summary.false_alarms == 2
    assert summary.pending == 0
    assert summary.false_alarm_rate == pytest.approx(2 / 3, abs=1e-3)
    assert summary.within_target is False


def test_false_alarm_tracker_window_evicts_oldest() -> None:
    tracker = FalseAlarmTracker("d1-test", window=2)
    tracker.record("a1", False)
    tracker.record("a2", True)
    tracker.record("a3", True)  # evicts a1
    summary = tracker.summary()
    assert summary.alerts_in_window == 2
    assert summary.false_alarms == 0


# --- calibration ------------------------------------------------------------


def test_brier_score_bounds() -> None:
    assert brier_score([1.0, 0.0], [True, False]) == 0.0
    assert brier_score([0.0, 1.0], [True, False]) == 1.0


def test_reliability_curve_bins_nonempty() -> None:
    probs = [0.05, 0.15, 0.85, 0.95]
    labels = [False, False, True, True]
    curve = reliability_curve(probs, labels, n_bins=10)
    assert curve
    assert all(0 <= b.mean_predicted <= 1 for b in curve)
    assert all(b.count >= 1 for b in curve)


def test_calibrator_identity_until_fit_then_recalibrates() -> None:
    cal = ConfidenceCalibrator(n_bins=5)
    assert cal.calibrate(0.7) == 0.7  # identity when unfitted
    cal.fit([0.9, 0.85, 0.1, 0.05], [False, False, False, False])
    assert cal.calibrated is True
    # A high raw score maps to the (all-negative) empirical frequency ~ 0.
    assert cal.calibrate(0.9) == pytest.approx(0.0, abs=1e-6)


# --- drift ------------------------------------------------------------------


def test_psi_zero_for_identical_and_positive_for_shift() -> None:
    base = [float(i) for i in range(100)]
    assert population_stability_index(base, base) == pytest.approx(0.0, abs=1e-6)
    shifted = [v + 100 for v in base]
    assert population_stability_index(base, shifted) > 0.25


def test_feature_drift_monitor_status_bands() -> None:
    base = {"f": [float(i) for i in range(100)]}
    monitor = FeatureDriftMonitor("d1-test", base, warn_psi=0.1, alert_psi=0.25)
    stable = monitor.check({"f": [float(i) for i in range(100)]})
    assert stable.status == "stable"
    drifted = monitor.check({"f": [v + 100 for v in base["f"]]})
    assert drifted.status == "drift"
    assert drifted.driven_by == "f"


# --- benchmark scaffold -----------------------------------------------------


def test_run_benchmark_aggregates_with_disclaimer() -> None:
    result: BenchmarkResult = run_benchmark(_dataset(), lambda f: f["x"], threshold=0.5)
    assert result.model_id == "d1-test"
    assert result.backtest.samples == 6
    assert 0.0 <= result.brier_score <= 1.0
    assert result.thresholds_preliminary is True
    assert result.pending_customer_calibration is True
    assert result.provenance.value == "preliminary"
    assert "preliminary" in result.disclaimer.lower()
