"""D1: the platform's first analytics-model framework (advisory, read-only).

``watertwin_models`` is the **D1 framework** -- a small, pure, deterministic
scaffold for the first tier of S3M-WaterTwin analytics models. It deliberately
does **not** implement any water/equipment physics itself: every concrete D1
model REUSES the single canonical physics engine (:mod:`watertwin_engineering`)
and the existing Water-Quality / Membrane service layer, and the framework only
provides the surrounding metadata, evaluation and monitoring machinery that a
model needs to be honest about what it is:

* :class:`ModelSpec` -- full, serializable model metadata (inputs, outputs,
  baseline, reused components with preserved provenance, alert thresholds, drift
  and calibration configuration). Every threshold is stamped **preliminary** and
  ``pending_customer_calibration=True``.
* a **back-test harness** (:mod:`.backtest`) that scores a model against a
  synthetic, labelled dataset and returns transparent metrics (precision,
  recall, F1, accuracy, false-alarm rate, lead time).
* a **false-alarm tracker** (:mod:`.false_alarm`) for online false-positive
  accounting against operator dispositions.
* a **confidence-calibration** layer (:mod:`.calibration`) -- reliability
  binning + Brier score (uncalibrated until customer-labelled data exists).
* a **drift hook** (:mod:`.drift`) -- population-stability-index feature-drift
  monitoring against a baseline reference.
* a **benchmark scaffold** (:mod:`.benchmark`) that aggregates the above into a
  single preliminary benchmark report.

The framework is strictly advisory: every artifact carries the read-only
:class:`~canonical_water_model.ControlBoundary` and
``provenance = preliminary``. Nothing here writes to any control system, and no
threshold is presented as validated -- all are preliminary pending customer
calibration.
"""

from __future__ import annotations

from watertwin_models.backtest import (
    BackTestDataset,
    BackTestMetrics,
    LabeledSample,
    run_backtest,
)
from watertwin_models.benchmark import BenchmarkResult, run_benchmark
from watertwin_models.calibration import (
    ConfidenceCalibrator,
    ReliabilityBin,
    brier_score,
    reliability_curve,
)
from watertwin_models.drift import (
    DriftReport,
    FeatureDriftMonitor,
    population_stability_index,
)
from watertwin_models.false_alarm import FalseAlarmSummary, FalseAlarmTracker
from watertwin_models.spec import (
    AlertThreshold,
    BaselineRef,
    CalibrationConfig,
    DriftConfig,
    FalseAlarmConfig,
    InputSignal,
    ModelSpec,
    ModelTier,
    ReusedComponent,
    ThresholdDirection,
)

__all__ = [
    # spec
    "AlertThreshold",
    # backtest
    "BackTestDataset",
    "BackTestMetrics",
    "BaselineRef",
    # benchmark
    "BenchmarkResult",
    "CalibrationConfig",
    # calibration
    "ConfidenceCalibrator",
    "DriftConfig",
    # drift
    "DriftReport",
    "FalseAlarmConfig",
    # false alarm
    "FalseAlarmSummary",
    "FalseAlarmTracker",
    "FeatureDriftMonitor",
    "InputSignal",
    "LabeledSample",
    "ModelSpec",
    "ModelTier",
    "ReliabilityBin",
    "ReusedComponent",
    "ThresholdDirection",
    "brier_score",
    "population_stability_index",
    "reliability_curve",
    "run_backtest",
    "run_benchmark",
]
