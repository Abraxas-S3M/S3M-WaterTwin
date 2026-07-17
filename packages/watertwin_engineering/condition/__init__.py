"""Condition-intelligence framework for advisory asset-condition models.

This sub-package turns the platform's pure engineering math into *governed,
evaluable* condition models. It provides the connective tissue an operator-facing
alert needs before it can be trusted:

* :mod:`.model_spec` -- the :class:`ModelSpec` **contract** every model must
  publish (equation source, feature spec, assumptions, valid range, version,
  uncertainty method, failure modes, explainability outputs) plus the
  :class:`ConditionModel` protocol, the uncertainty-bearing
  :class:`ConditionScore`, and a transparent reference model
  (:class:`ThresholdConditionModel`);
* :mod:`.backtest` -- a **back-test harness** that runs a model over a labelled
  or synthetic history and reports precision, recall, false-alarm rate and lead
  time (with Wilson confidence intervals);
* :mod:`.calibration` -- a **confidence-calibration** step (reliability
  histogram, ECE/MCE, Brier score, recalibration map); and
* :mod:`.drift` -- a **drift monitor** comparing live feature/score
  distributions to a baseline window and raising a drift flag.

Every output carries an uncertainty bound and a ``provenance`` stamp, and nothing
here performs I/O or touches any control system. Operator feedback capture
(confirm/dismiss on an alert) is persisted by the service layer's durable store,
which reuses the same append-only audit trail.
"""

from __future__ import annotations

from .backtest import (
    BackTestMetrics,
    BackTestResult,
    run_backtest,
    wilson_interval,
)
from .calibration import (
    CalibrationBin,
    CalibrationResult,
    calibrate,
)
from .drift import (
    DEFAULT_PSI_THRESHOLD,
    SCORE_FEATURE,
    DriftResult,
    FeatureDrift,
    monitor_drift,
    population_stability_index,
)
from .model_spec import (
    DEFAULT_COVERAGE,
    PRELIMINARY,
    ConditionModel,
    ConditionScore,
    FeatureContribution,
    FeatureSpec,
    ModelSpec,
    ThresholdConditionModel,
    UncertaintyMethod,
    ValidRange,
    clamp,
)

__all__ = [
    "DEFAULT_COVERAGE",
    "DEFAULT_PSI_THRESHOLD",
    "PRELIMINARY",
    "SCORE_FEATURE",
    "BackTestMetrics",
    "BackTestResult",
    "CalibrationBin",
    "CalibrationResult",
    "ConditionModel",
    "ConditionScore",
    "DriftResult",
    "FeatureContribution",
    "FeatureDrift",
    "FeatureSpec",
    "ModelSpec",
    "ThresholdConditionModel",
    "UncertaintyMethod",
    "ValidRange",
    "calibrate",
    "clamp",
    "monitor_drift",
    "population_stability_index",
    "run_backtest",
    "wilson_interval",
]
