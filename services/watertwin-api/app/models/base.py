"""Shared output schema + adapter contract for the D1 models.

Defines the common, JSON-serializable :class:`ModelAssessment` every D1 model
emits (indices, probabilities, explainable contributions, ranked causes,
threshold-triggered alerts, calibrated confidence, drift status), the
:class:`TriggeredAlert` produced when a preliminary threshold is crossed, the
:func:`evaluate_thresholds` helper, and the :class:`ModelAdapter` protocol that
ties a :class:`~watertwin_models.ModelSpec` to its assessment, back-test dataset,
drift hook and benchmark.

Everything is advisory and read-only: assessments carry the
:class:`~canonical_water_model.ControlBoundary` and ``provenance = preliminary``.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from canonical_water_model import (
    ControlBoundary,
    DataProvenance,
    Evidence,
    HealthContribution,
    RankedCause,
    now_iso,
)
from watertwin_models import (
    AlertThreshold,
    BackTestDataset,
    BackTestMetrics,
    BenchmarkResult,
    DriftReport,
    FeatureDriftMonitor,
    ModelSpec,
    ThresholdDirection,
    run_backtest,
    run_benchmark,
)


class TriggeredAlert(BaseModel):
    """A preliminary alert raised when an input crossed a preliminary threshold."""

    name: str
    metric: str
    observed: float
    threshold: float
    direction: ThresholdDirection
    severity: str
    rationale: str
    preliminary: bool = True
    pending_customer_calibration: bool = True


class ModelAssessment(BaseModel):
    """The advisory, read-only output of a D1 model for one asset."""

    model_config = {"protected_namespaces": ()}

    model_id: str
    model_version: str
    asset_id: str
    indices: dict[str, float] = Field(default_factory=dict)
    probabilities: dict[str, float] = Field(default_factory=dict)
    band: str | None = None
    contributions: list[HealthContribution] = Field(default_factory=list)
    ranked_causes: list[RankedCause] = Field(default_factory=list)
    triggered_alerts: list[TriggeredAlert] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    confidence_calibrated: bool = False
    drift: DriftReport | None = None
    evidence: Evidence
    provenance: DataProvenance = DataProvenance.preliminary
    control_boundary: ControlBoundary = Field(default_factory=ControlBoundary)
    created_at: str = Field(default_factory=now_iso)


def evaluate_thresholds(
    thresholds: list[AlertThreshold],
    observed: dict[str, float],
) -> list[TriggeredAlert]:
    """Return the preliminary alerts crossed by the ``observed`` metric values."""
    triggered: list[TriggeredAlert] = []
    for th in thresholds:
        if th.metric not in observed:
            continue
        value = float(observed[th.metric])
        crossed = (
            value >= th.value
            if th.direction == ThresholdDirection.above
            else value <= th.value
        )
        if crossed:
            triggered.append(
                TriggeredAlert(
                    name=th.name,
                    metric=th.metric,
                    observed=round(value, 4),
                    threshold=th.value,
                    direction=th.direction,
                    severity=th.severity,
                    rationale=th.rationale,
                )
            )
    return triggered


class ModelAdapter(Protocol):
    """The contract binding a D1 model spec to its runtime behaviour."""

    spec: ModelSpec

    def assess(self, inputs: dict[str, float] | None = None) -> ModelAssessment:
        """Produce the advisory assessment for the reference asset."""
        ...

    def risk_score(self, features: dict[str, float]) -> float:
        """Scalar probability in ``[0, 1]`` of the labelled condition (back-test)."""
        ...

    def backtest_dataset(self) -> BackTestDataset:
        """The synthetic, labelled back-test dataset."""
        ...

    def drift_monitor(self) -> FeatureDriftMonitor:
        """The baseline-seeded drift hook."""
        ...

    def backtest(self, threshold: float | None = None) -> BackTestMetrics:
        """Back-test metrics from the D1 harness."""
        ...

    def benchmark(self) -> BenchmarkResult:
        """Preliminary benchmark scaffold result."""
        ...


# Re-export so concrete model modules import their toolkit from one place.
__all__ = [
    "ModelAdapter",
    "ModelAssessment",
    "TriggeredAlert",
    "evaluate_thresholds",
    "run_backtest",
    "run_benchmark",
]
