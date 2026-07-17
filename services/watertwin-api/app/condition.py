"""Condition-Intelligence service layer (advisory, read-only).

Wires the pure :mod:`watertwin_engineering.condition` framework into the API. It
publishes a small registry of **governed** condition models -- each carrying a
full :class:`~watertwin_engineering.condition.model_spec.ModelSpec` contract
(equation source, feature spec, assumptions, valid range, version, uncertainty
method, failure modes, explainability outputs) -- and exposes, per model:

* a **back-test** over a deterministic synthetic-but-labelled fouling history
  (precision, recall, false-alarm rate, lead time, all with uncertainty);
* a **confidence-calibration** reliability report; and
* a **drift** check comparing a shifted live window to the frozen baseline.

Operator confirm/dismiss feedback on an alert is persisted by the durable
``Store`` (``app.store``), which the API routes through the existing audit trail.

Everything here is advisory and preliminary: scores, metrics and forecasts are
screening-grade estimates with uncertainty bounds and a ``provenance`` stamp, and
nothing writes to any control system.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from watertwin_engineering.condition import (
    ConditionScore,
    FeatureSpec,
    ModelSpec,
    ThresholdConditionModel,
    UncertaintyMethod,
    ValidRange,
    calibrate,
    monitor_drift,
    run_backtest,
)

#: Deterministic seed so every synthetic history/window is reproducible.
_SEED = 20240717


@dataclass(frozen=True)
class ConditionModelBundle:
    """A governed model plus the synthetic-history parameters that exercise it."""

    model: ThresholdConditionModel
    #: Ground-truth feature value at/above which the asset is *genuinely* in an
    #: event state (labels the synthetic history independently of the model).
    event_threshold: float
    baseline_center: float
    baseline_sigma: float
    #: Live-window mean used to demonstrate drift (a shifted operating regime).
    drift_center: float

    @property
    def feature(self) -> str:
        return self.model.feature


def _dp_fouling_model() -> ConditionModelBundle:
    spec = ModelSpec(
        model_id="normalized-dp-fouling",
        version="1.0.0",
        description=(
            "Membrane/cartridge fouling severity from the normalized "
            "differential-pressure ratio (live dP normalized to clean-baseline "
            "dP at reference flow/temperature)."
        ),
        equation_source=(
            "watertwin_engineering.water_quality.normalized_differential_pressure "
            "(ASTM D4516-style flow/temperature normalization); severity is a "
            "linear ramp on the normalized ratio."
        ),
        feature_spec=(
            FeatureSpec(
                name="normalized_dp_ratio",
                unit="dimensionless",
                description="Normalized differential pressure / clean-baseline dP.",
            ),
        ),
        assumptions=(
            "dP is already normalized to a clean-baseline flow and temperature.",
            "A rising normalized dP is driven by fouling, not a sensor fault.",
            "Clean-baseline reference was captured on a representative feed.",
        ),
        valid_range=ValidRange({"normalized_dp_ratio": (0.8, 3.0)}),
        uncertainty_method=UncertaintyMethod(
            name="residual-sigma",
            description=(
                "Feature measurement sigma propagated through the ramp slope at "
                "a 95% normal coverage."
            ),
            coverage=0.95,
        ),
        failure_modes=(
            "A dP-transmitter drift is read as fouling (mitigated by cross-checks).",
            "Extrapolates poorly outside the [0.8, 3.0] normalized range.",
            "Cannot distinguish scaling from organic/particulate fouling.",
        ),
        explainability_outputs=(
            "per-feature contribution",
            "margin to warn/alarm thresholds",
            "uncertainty band [lower, upper]",
        ),
    )
    model = ThresholdConditionModel(
        spec=spec,
        feature="normalized_dp_ratio",
        warn_at=1.15,
        alarm_at=1.50,
        feature_sigma=0.03,
        alarm_score_threshold=0.5,
    )
    return ConditionModelBundle(
        model=model,
        event_threshold=1.40,
        baseline_center=1.02,
        baseline_sigma=0.03,
        drift_center=1.28,
    )


def _salt_passage_model() -> ConditionModelBundle:
    spec = ModelSpec(
        model_id="salt-passage-integrity",
        version="1.0.0",
        description=(
            "Membrane integrity / salt-passage breakthrough severity from the "
            "normalized salt-passage ratio (live salt passage vs clean baseline)."
        ),
        equation_source=(
            "watertwin_engineering.water_quality.normalized_salt_passage "
            "(temperature/recovery normalization); severity is a linear ramp on "
            "the normalized ratio."
        ),
        feature_spec=(
            FeatureSpec(
                name="normalized_salt_passage_ratio",
                unit="dimensionless",
                description="Normalized salt passage / clean-baseline passage.",
            ),
        ),
        assumptions=(
            "Salt passage is normalized to clean-baseline temperature and recovery.",
            "Permeate conductivity sensors are calibrated and consistent.",
            "A rising ratio reflects membrane integrity loss, not feed excursion.",
        ),
        valid_range=ValidRange({"normalized_salt_passage_ratio": (0.8, 3.0)}),
        uncertainty_method=UncertaintyMethod(
            name="residual-sigma",
            description=(
                "Feature measurement sigma propagated through the ramp slope at "
                "a 95% normal coverage."
            ),
            coverage=0.95,
        ),
        failure_modes=(
            "A feed-salinity excursion inflates the ratio without integrity loss.",
            "Permeate-conductivity sensor error masquerades as breakthrough.",
            "Extrapolates poorly outside the [0.8, 3.0] normalized range.",
        ),
        explainability_outputs=(
            "per-feature contribution",
            "margin to warn/alarm thresholds",
            "uncertainty band [lower, upper]",
        ),
    )
    model = ThresholdConditionModel(
        spec=spec,
        feature="normalized_salt_passage_ratio",
        warn_at=1.10,
        alarm_at=1.40,
        feature_sigma=0.03,
        alarm_score_threshold=0.5,
    )
    return ConditionModelBundle(
        model=model,
        event_threshold=1.32,
        baseline_center=1.01,
        baseline_sigma=0.03,
        drift_center=1.22,
    )


#: The governed condition models exposed by the service, keyed by model id.
MODELS: dict[str, ConditionModelBundle] = {
    bundle.model.spec.model_id: bundle
    for bundle in (_dp_fouling_model(), _salt_passage_model())
}


def list_model_ids() -> list[str]:
    """Return the ids of every governed condition model."""
    return list(MODELS)


def _bundle(model_id: str) -> ConditionModelBundle:
    bundle = MODELS.get(model_id)
    if bundle is None:
        raise KeyError(model_id)
    return bundle


def synthetic_history(model_id: str) -> list[dict[str, Any]]:
    """A deterministic labelled history: nominal duty then a fouling ramp.

    Labels are assigned independently of the model (ground truth = the feature
    reaching the bundle's ``event_threshold``), so the back-test measures the
    model rather than tautologically confirming it.
    """
    bundle = _bundle(model_id)
    rng = random.Random(_SEED)
    feature = bundle.feature
    records: list[dict[str, Any]] = []
    t = 0

    for _ in range(40):
        value = bundle.baseline_center + rng.gauss(0.0, bundle.baseline_sigma)
        records.append(
            {"t": t, "features": {feature: value}, "label": value >= bundle.event_threshold}
        )
        t += 1

    start = bundle.baseline_center
    end = bundle.model.alarm_at + 0.20
    for i in range(20):
        frac = (i + 1) / 20
        value = start + (end - start) * frac + rng.gauss(0.0, bundle.baseline_sigma)
        records.append(
            {"t": t, "features": {feature: value}, "label": value >= bundle.event_threshold}
        )
        t += 1
    return records


def baseline_window(model_id: str, size: int = 60) -> list[dict[str, Any]]:
    """A frozen baseline window drawn from the model's nominal operating regime."""
    bundle = _bundle(model_id)
    rng = random.Random(_SEED + 1)
    feature = bundle.feature
    return [
        {"features": {feature: bundle.baseline_center + rng.gauss(0.0, bundle.baseline_sigma)}}
        for _ in range(size)
    ]


def live_window(model_id: str, size: int = 60, *, shifted: bool = True) -> list[dict[str, Any]]:
    """A live window. ``shifted`` moves the mean to a drifted regime (default)."""
    bundle = _bundle(model_id)
    rng = random.Random(_SEED + 2)
    feature = bundle.feature
    center = bundle.drift_center if shifted else bundle.baseline_center
    return [
        {"features": {feature: center + rng.gauss(0.0, bundle.baseline_sigma)}}
        for _ in range(size)
    ]


def score(model_id: str, features: Mapping[str, float]) -> ConditionScore:
    """Score a live feature vector with the model (advisory, with uncertainty)."""
    return _bundle(model_id).model.score(features)


def model_spec_dict(model_id: str) -> dict[str, Any]:
    """The full published contract for a model, as a JSON-serializable dict."""
    return asdict(_bundle(model_id).model.spec)


def backtest_dict(model_id: str) -> dict[str, Any]:
    """Back-test the model over its synthetic labelled history."""
    bundle = _bundle(model_id)
    result = run_backtest(bundle.model, synthetic_history(model_id), lead_window=float("inf"))
    return asdict(result)


def calibration_dict(model_id: str, n_bins: int = 10) -> dict[str, Any]:
    """Confidence-calibration reliability report over the synthetic history."""
    bundle = _bundle(model_id)
    history = synthetic_history(model_id)
    scores = [bundle.model.score(r["features"]).score for r in history]
    labels = [bool(r["label"]) for r in history]
    return asdict(calibrate(scores, labels, n_bins=n_bins))


def drift_dict(model_id: str, *, shifted: bool = True) -> dict[str, Any]:
    """Drift report comparing a (by default shifted) live window to the baseline."""
    bundle = _bundle(model_id)
    result = monitor_drift(
        baseline_window(model_id),
        live_window(model_id, shifted=shifted),
        model=bundle.model,
    )
    return asdict(result)
