"""The model contract for the condition-intelligence framework.

Every condition model in this package is *governed by a contract*. Before a model
is trusted to raise an operator-facing alert it must publish a :class:`ModelSpec`
that documents, in one auditable place:

* ``equation_source`` -- the physics/engineering reference (or paper/standard)
  the score is derived from, so the math is never a black box;
* ``feature_spec`` -- exactly which inputs the model consumes, with units;
* ``assumptions`` -- the conditions under which the model is valid;
* ``valid_range`` -- the applicability domain (per-feature bounds); a score
  computed outside this domain is flagged as an extrapolation;
* ``version`` -- so a stored score can be traced to the exact model revision;
* ``uncertainty_method`` -- how the reported ``[lower, upper]`` band is derived;
* ``failure_modes`` -- the known ways the model can be wrong (documented, not
  hidden); and
* ``explainability_outputs`` -- what per-score explanation the model emits.

Like the rest of :mod:`watertwin_engineering` everything here is pure and
deterministic: no I/O, and identical inputs always yield identical outputs. A
score is **advisory and preliminary** -- every :class:`ConditionScore` carries an
uncertainty band and a ``provenance`` stamp, and no model writes to any control
system.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

#: Provenance marker stamped on every advisory condition output.
PRELIMINARY = "preliminary"

#: Nominal two-sided coverage of a reported uncertainty band (95%).
DEFAULT_COVERAGE = 0.95

#: z-multiplier for a two-sided 95% band under a normal residual assumption.
_Z_95 = 1.959963984540054

__all__ = [
    "DEFAULT_COVERAGE",
    "PRELIMINARY",
    "ConditionModel",
    "ConditionScore",
    "FeatureContribution",
    "FeatureSpec",
    "ModelSpec",
    "ThresholdConditionModel",
    "UncertaintyMethod",
    "ValidRange",
    "clamp",
]


def clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` to the inclusive ``[low, high]`` interval."""
    return max(low, min(high, value))


@dataclass(frozen=True)
class FeatureSpec:
    """One input feature a model consumes, with its engineering unit."""

    name: str
    unit: str
    description: str = ""


@dataclass(frozen=True)
class ValidRange:
    """The model's applicability domain: inclusive ``[low, high]`` per feature.

    A score requested for a feature vector that falls outside these bounds is an
    *extrapolation*: the model still returns a value but marks it so downstream
    consumers can widen uncertainty or suppress the alert.
    """

    bounds: Mapping[str, tuple[float, float]]

    def __post_init__(self) -> None:
        for name, (low, high) in self.bounds.items():
            if low > high:
                raise ValueError(
                    f"valid_range for {name!r} has low {low} > high {high}."
                )

    def violations(self, features: Mapping[str, float]) -> list[str]:
        """Return a human-readable reason for each out-of-domain feature."""
        out: list[str] = []
        for name, (low, high) in self.bounds.items():
            if name not in features or features[name] is None:
                continue
            value = float(features[name])
            if value < low or value > high:
                out.append(
                    f"{name}={value:g} outside valid range [{low:g}, {high:g}]"
                )
        return out

    def contains(self, features: Mapping[str, float]) -> bool:
        """True when every bounded feature present in ``features`` is in range."""
        return not self.violations(features)


@dataclass(frozen=True)
class UncertaintyMethod:
    """How a model derives the ``[lower, upper]`` band around its score."""

    name: str
    description: str
    coverage: float = DEFAULT_COVERAGE

    def __post_init__(self) -> None:
        if not 0.0 < self.coverage < 1.0:
            raise ValueError("coverage must be in (0, 1).")


@dataclass(frozen=True)
class ModelSpec:
    """The publishable contract every condition model must satisfy.

    Construction is permissive; call :meth:`validate` (also invoked by the
    framework's harnesses) to enforce that every required part of the contract is
    present and non-empty.
    """

    model_id: str
    version: str
    description: str
    equation_source: str
    feature_spec: tuple[FeatureSpec, ...]
    assumptions: tuple[str, ...]
    valid_range: ValidRange
    uncertainty_method: UncertaintyMethod
    failure_modes: tuple[str, ...]
    explainability_outputs: tuple[str, ...]
    provenance: str = PRELIMINARY

    def feature_names(self) -> list[str]:
        """The ordered names of the features this model consumes."""
        return [f.name for f in self.feature_spec]

    def validate(self) -> None:
        """Raise :class:`ValueError` unless the full contract is populated.

        Enforces that a model cannot be back-tested, scored or shipped without
        an equation source, a feature spec, assumptions, a valid range, a
        version, an uncertainty method, documented failure modes and declared
        explainability outputs.
        """
        required_text = {
            "model_id": self.model_id,
            "version": self.version,
            "description": self.description,
            "equation_source": self.equation_source,
        }
        for name, value in required_text.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"ModelSpec.{name} must be a non-empty string.")

        if not self.feature_spec:
            raise ValueError("ModelSpec.feature_spec must list at least one feature.")
        seen: set[str] = set()
        for fs in self.feature_spec:
            if not fs.name or not fs.unit:
                raise ValueError("every FeatureSpec needs a name and a unit.")
            if fs.name in seen:
                raise ValueError(f"duplicate feature in feature_spec: {fs.name!r}.")
            seen.add(fs.name)

        if not self.assumptions:
            raise ValueError("ModelSpec.assumptions must document at least one assumption.")
        if not self.valid_range.bounds:
            raise ValueError("ModelSpec.valid_range must bound at least one feature.")
        if not isinstance(self.uncertainty_method, UncertaintyMethod):
            raise ValueError("ModelSpec.uncertainty_method must be an UncertaintyMethod.")
        if not self.failure_modes:
            raise ValueError("ModelSpec.failure_modes must document at least one failure mode.")
        if not self.explainability_outputs:
            raise ValueError(
                "ModelSpec.explainability_outputs must declare at least one output."
            )


@dataclass(frozen=True)
class FeatureContribution:
    """One transparent driver of a condition score (explainability output)."""

    feature: str
    contribution: float
    detail: str


@dataclass(frozen=True)
class ConditionScore:
    """A single advisory condition score with uncertainty and provenance.

    ``score`` is a severity in ``[0, 1]`` (0 = nominal, 1 = fully degraded);
    ``lower``/``upper`` bracket it at the model's declared coverage;
    ``alarm`` is the model's decision at its own alarm threshold; and
    ``contributions`` explain *why* the score landed where it did.
    """

    model_id: str
    version: str
    score: float
    alarm: bool
    lower: float
    upper: float
    confidence: float
    in_valid_range: bool
    contributions: list[FeatureContribution] = field(default_factory=list)
    range_violations: list[str] = field(default_factory=list)
    provenance: str = PRELIMINARY


@runtime_checkable
class ConditionModel(Protocol):
    """A condition model: a published :attr:`spec` plus a pure :meth:`score`."""

    @property
    def spec(self) -> ModelSpec:  # pragma: no cover - structural protocol
        ...

    def score(self, features: Mapping[str, float]) -> ConditionScore:  # pragma: no cover
        ...


@dataclass(frozen=True)
class ThresholdConditionModel:
    """A transparent single-feature threshold model (reference implementation).

    The severity ramps linearly from ``0`` at ``warn_at`` to ``1`` at
    ``alarm_at`` for the monitored feature (either direction is supported: set
    ``alarm_at`` below ``warn_at`` to alarm on a *falling* signal). The
    uncertainty band is a residual-sigma band on the feature propagated through
    the ramp slope. An alarm fires when the severity reaches
    ``alarm_score_threshold``.

    This is intentionally simple and fully explainable so it can serve as the
    canonical worked example for the back-test, calibration and drift harnesses;
    it satisfies the same :class:`ConditionModel` protocol a physics-derived
    model would.
    """

    spec: ModelSpec
    feature: str
    warn_at: float
    alarm_at: float
    feature_sigma: float = 0.0
    alarm_score_threshold: float = 0.5

    def __post_init__(self) -> None:
        if self.alarm_at == self.warn_at:
            raise ValueError("alarm_at must differ from warn_at.")
        if self.feature_sigma < 0:
            raise ValueError("feature_sigma must be non-negative.")
        if not 0.0 <= self.alarm_score_threshold <= 1.0:
            raise ValueError("alarm_score_threshold must be in [0, 1].")

    def _severity(self, value: float) -> float:
        return clamp((value - self.warn_at) / (self.alarm_at - self.warn_at), 0.0, 1.0)

    def score(self, features: Mapping[str, float]) -> ConditionScore:
        """Score a feature vector, returning severity + band + explanation."""
        if self.feature not in features or features[self.feature] is None:
            raise ValueError(f"features is missing monitored feature {self.feature!r}.")
        value = float(features[self.feature])
        severity = self._severity(value)

        # Residual-sigma band: propagate the feature sigma through the ramp
        # slope (1 / span) and a normal coverage multiplier, clamped to [0, 1].
        span = abs(self.alarm_at - self.warn_at)
        half = (_Z_95 * self.feature_sigma / span) if span > 0 else 0.0
        lower = clamp(severity - half, 0.0, 1.0)
        upper = clamp(severity + half, 0.0, 1.0)
        # Confidence shrinks as the band widens (a 1.0-wide band -> 0 confidence).
        confidence = round(clamp(1.0 - (upper - lower), 0.0, 1.0), 4)

        violations = self.spec.valid_range.violations(features)
        margin = value - self.alarm_at
        contributions = [
            FeatureContribution(
                feature=self.feature,
                contribution=round(severity, 4),
                detail=(
                    f"{self.feature}={value:g} vs warn {self.warn_at:g} / "
                    f"alarm {self.alarm_at:g} (margin {margin:+g})"
                ),
            )
        ]
        return ConditionScore(
            model_id=self.spec.model_id,
            version=self.spec.version,
            score=round(severity, 4),
            alarm=severity >= self.alarm_score_threshold,
            lower=round(lower, 4),
            upper=round(upper, 4),
            confidence=confidence,
            in_valid_range=not violations,
            contributions=contributions,
            range_violations=violations,
            provenance=self.spec.provenance,
        )
