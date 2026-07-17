"""D1 :class:`ModelSpec` and its supporting metadata types.

A :class:`ModelSpec` is the full, serializable descriptor of a D1 model: what it
consumes, what it emits, the baseline it is normalized against, the canonical
components it REUSES (with their provenance preserved), its **preliminary** alert
thresholds, and its drift / calibration / false-alarm configuration.

All types are Pydantic v2 models so a spec round-trips cleanly to JSON for the
API. Every threshold and configuration is marked ``preliminary`` and
``pending_customer_calibration=True`` -- the platform never presents a D1
threshold as validated. Specs carry the read-only control boundary; a model is
advisory only and never writes to a control system.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from canonical_water_model import ControlBoundary, DataProvenance, now_iso


class ModelTier(str, Enum):
    """Analytics-model maturity tier.

    ``D1`` is the first tier: transparent, physics-reusing detection/diagnostic
    models with preliminary thresholds pending customer calibration.
    """

    D1 = "D1"


class ThresholdDirection(str, Enum):
    """Whether an alert fires when a metric is above or below the threshold."""

    above = "above"
    below = "below"


class InputSignal(BaseModel):
    """One input signal a model consumes, with its unit and origin."""

    name: str
    unit: str
    description: str
    #: telemetry (live tag), derived (computed by a reused component),
    #: history (maintenance/operational record) or chemistry (ion analysis).
    source: str = "telemetry"


class AlertThreshold(BaseModel):
    """A single **preliminary** alert threshold.

    ``direction`` says whether the alert fires above or below ``value`` for
    ``metric``. Every threshold is preliminary and
    ``pending_customer_calibration`` -- it is a documented screening default, not
    a validated set-point.
    """

    name: str
    metric: str
    direction: ThresholdDirection
    value: float
    severity: str  # "watch" | "warning" | "critical"
    rationale: str
    preliminary: bool = True
    pending_customer_calibration: bool = True
    provenance: DataProvenance = DataProvenance.preliminary


class BaselineRef(BaseModel):
    """The reference baseline a model normalizes/compares against."""

    name: str
    description: str
    reference_values: dict[str, float] = Field(default_factory=dict)
    source: str
    provenance: DataProvenance = DataProvenance.preliminary


class ReusedComponent(BaseModel):
    """A canonical component the model REUSES (never duplicates).

    Documents exactly which existing physics / service layer produces a piece of
    the model output, with the provenance of that layer preserved end-to-end.
    """

    name: str
    module: str
    purpose: str
    provenance: DataProvenance = DataProvenance.preliminary


class DriftConfig(BaseModel):
    """Configuration for the population-stability-index drift hook.

    ``features`` are the input signals monitored for distribution drift against
    the model baseline; ``warn_psi`` / ``alert_psi`` are the **preliminary** PSI
    bands (the conventional 0.10 / 0.25 screening bands), pending customer
    calibration on the site's own data.
    """

    features: list[str] = Field(default_factory=list)
    method: str = "population_stability_index"
    warn_psi: float = 0.10
    alert_psi: float = 0.25
    preliminary: bool = True
    pending_customer_calibration: bool = True


class CalibrationConfig(BaseModel):
    """Confidence-calibration configuration.

    D1 confidences are reported through a reliability-binning calibrator but are
    **not** calibrated until customer-labelled outcomes exist
    (``calibrated=False``); until then the raw physics-derived confidence is
    passed through unchanged and flagged as preliminary.
    """

    method: str = "reliability_binning"
    n_bins: int = 10
    calibrated: bool = False
    notes: str = (
        "Uncalibrated: confidence is a preliminary physics-derived qualifier. "
        "Awaiting customer-labelled outcomes to fit and validate calibration."
    )
    pending_customer_calibration: bool = True


class FalseAlarmConfig(BaseModel):
    """False-alarm tracking configuration (preliminary target)."""

    window: int = 100
    target_false_alarm_rate: float = 0.05
    preliminary: bool = True
    pending_customer_calibration: bool = True


class ModelSpec(BaseModel):
    """Full metadata for a D1 analytics model (advisory, read-only).

    Captures the model identity, the inputs it consumes and outputs it emits, the
    baseline it is normalized against, the canonical components it REUSES (with
    preserved provenance), its preliminary alert thresholds, and its drift /
    calibration / false-alarm configuration. Everything is preliminary; the
    control boundary is read-only.
    """

    # ``model_`` is a Pydantic-protected prefix; opt out so ``model_id`` is a
    # plain field (D1 specs are metadata, not Pydantic model internals).
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    version: str
    name: str
    tier: ModelTier = ModelTier.D1
    status: str = "preliminary"
    description: str
    asset_type: str
    target: str
    outputs: list[str] = Field(default_factory=list)
    inputs: list[InputSignal] = Field(default_factory=list)
    baseline: BaselineRef
    thresholds: list[AlertThreshold] = Field(default_factory=list)
    reused_components: list[ReusedComponent] = Field(default_factory=list)
    drift: DriftConfig = Field(default_factory=DriftConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    false_alarm: FalseAlarmConfig = Field(default_factory=FalseAlarmConfig)
    assumptions: list[str] = Field(default_factory=list)
    provenance: DataProvenance = DataProvenance.preliminary
    control_boundary: ControlBoundary = Field(default_factory=ControlBoundary)
    created_at: str = Field(default_factory=now_iso)
