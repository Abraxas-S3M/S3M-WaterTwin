"""Canonical water asset, stream, telemetry, and packet model.

Shared Pydantic v2 model package used by every S3M-WaterTwin service. It defines
the canonical enums, data models, and small helpers for water treatment assets,
process streams, telemetry, health, anomalies, and recommendation packets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

__all__ = [
    "AssetType",
    "TreatmentStage",
    "StreamType",
    "Criticality",
    "HealthBand",
    "AnomalyDomain",
    "DataProvenance",
    "ApprovalStatus",
    "RatedData",
    "Asset",
    "WaterStream",
    "SamplingPoint",
    "TelemetryReading",
    "HealthContribution",
    "HealthScore",
    "AnomalyResult",
    "ControlBoundary",
    "Evidence",
    "RankedCause",
    "WaterTwinPacket",
    "RecommendationCard",
    "SampleType",
    "QCStatus",
    "WaterQualitySample",
    "ContaminantMatrixRow",
    "ScalingRisk",
    "WaterQualityForecast",
    "WQAlert",
    "ComponentHealth",
    "OperatingEnvelope",
    "RemainingUsefulLife",
    "FailureProbability",
    "MaintenancePriority",
    "RootCauseRanking",
    "FoulingSeverity",
    "MembraneHealth",
    "PdMRecommendation",
    "now_iso",
]


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


class AssetType(str, Enum):
    intake_pump = "intake_pump"
    transfer_pump = "transfer_pump"
    hp_pump = "hp_pump"
    booster_pump = "booster_pump"
    permeate_pump = "permeate_pump"
    brine_pump = "brine_pump"
    dosing_pump = "dosing_pump"
    motor = "motor"
    vfd = "vfd"
    erd = "erd"
    cartridge_filter = "cartridge_filter"
    control_valve = "control_valve"
    membrane_array = "membrane_array"
    transformer = "transformer"
    generator = "generator"
    sensor = "sensor"


class TreatmentStage(str, Enum):
    intake = "intake"
    screening = "screening"
    pretreatment = "pretreatment"
    media_filtration = "media_filtration"
    cartridge_filtration = "cartridge_filtration"
    dosing = "dosing"
    high_pressure_pumping = "high_pressure_pumping"
    ro_stage_1 = "ro_stage_1"
    ro_stage_2 = "ro_stage_2"
    permeate = "permeate"
    remineralization = "remineralization"
    disinfection = "disinfection"
    finished_water = "finished_water"
    distribution_handoff = "distribution_handoff"
    concentrate_discharge = "concentrate_discharge"


class StreamType(str, Enum):
    seawater_feed = "seawater_feed"
    pretreated_feed = "pretreated_feed"
    ro_feed = "ro_feed"
    permeate = "permeate"
    concentrate = "concentrate"
    product_water = "product_water"


class Criticality(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class HealthBand(str, Enum):
    Healthy = "Healthy"
    Monitor = "Monitor"
    Degraded = "Degraded"
    HighRisk = "HighRisk"
    Critical = "Critical"

    @classmethod
    def from_score(cls, score: float) -> "HealthBand":
        """Map a 0-100 health score onto its band."""
        if score >= 90:
            return cls.Healthy
        if score >= 75:
            return cls.Monitor
        if score >= 60:
            return cls.Degraded
        if score >= 40:
            return cls.HighRisk
        return cls.Critical


class AnomalyDomain(str, Enum):
    mechanical = "mechanical"
    hydraulic = "hydraulic"
    electrical = "electrical"
    process = "process"
    membrane = "membrane"
    water_quality = "water_quality"
    sensor = "sensor"
    cyber_physical = "cyber_physical"


class DataProvenance(str, Enum):
    synthetic = "synthetic"
    simulated = "simulated"
    preliminary = "preliminary"
    measured = "measured"


class ApprovalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class RatedData(BaseModel):
    rated_flow_m3h: Optional[float] = None
    rated_head_m: Optional[float] = None
    rated_power_kw: Optional[float] = None
    rated_speed_rpm: Optional[float] = None
    bep_flow_m3h: Optional[float] = None
    min_flow_m3h: Optional[float] = None
    max_flow_m3h: Optional[float] = None
    temp_limit_c: Optional[float] = None
    vibration_limit_mm_s: Optional[float] = None


class Asset(BaseModel):
    asset_id: str
    name: str
    asset_type: AssetType
    facility_id: str
    train_id: str
    treatment_stage: Optional[TreatmentStage] = None
    parent_id: Optional[str] = None
    manufacturer: str
    model: str
    serial_number: str
    location: str
    criticality: Criticality
    rated: RatedData
    install_date: Optional[str] = None


class WaterStream(BaseModel):
    stream_id: str
    stream_type: StreamType
    from_stage: TreatmentStage
    to_stage: TreatmentStage
    description: str


class SamplingPoint(BaseModel):
    point_id: str
    name: str
    stage: TreatmentStage
    stream_id: str
    location: str


class TelemetryReading(BaseModel):
    asset_id: str
    metric: str
    value: float
    unit: str
    timestamp: str
    provenance: DataProvenance = DataProvenance.synthetic
    quality: Optional[str] = None


class HealthContribution(BaseModel):
    factor: str
    delta: float
    detail: str


class HealthScore(BaseModel):
    asset_id: str
    score: float = Field(ge=0, le=100)
    band: HealthBand
    contributions: list[HealthContribution] = Field(default_factory=list)
    provenance: DataProvenance = DataProvenance.preliminary


class AnomalyResult(BaseModel):
    asset_id: str
    score: float = Field(ge=0, le=1)
    ranked_domains: list[tuple[AnomalyDomain, float]] = Field(default_factory=list)
    factors: dict[str, float] = Field(default_factory=dict)
    provenance: DataProvenance = DataProvenance.preliminary


class ControlBoundary(BaseModel):
    control_mode: str = "advisory"
    operator_approval_required: bool = True
    control_write_enabled: bool = False


class Evidence(BaseModel):
    telemetry_window: str
    assets_reviewed: list[str] = Field(default_factory=list)
    documents_reviewed: list[str] = Field(default_factory=list)
    simulation_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    data_timestamp: str


class RankedCause(BaseModel):
    cause: str
    probability: float
    evidence: str


class WaterTwinPacket(BaseModel):
    packet_id: str
    domain: str = "water_infrastructure"
    packet_type: str
    source: str = "s3m-watertwin"
    track: str
    facility_id: str
    train_id: str
    asset_id: Optional[str] = None
    treatment_stage: Optional[TreatmentStage] = None
    requested_outputs: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)
    evidence: Evidence
    control_boundary: ControlBoundary = Field(default_factory=ControlBoundary)


class RecommendationCard(BaseModel):
    recommendation_id: str
    packet_id: str
    facility_id: str
    train_id: str
    asset_id: Optional[str] = None
    treatment_stage: Optional[TreatmentStage] = None
    summary: str
    ranked_causes: list[RankedCause] = Field(default_factory=list)
    recommended_action: str
    confidence: float
    evidence: Evidence
    control_boundary: ControlBoundary = Field(default_factory=ControlBoundary)
    approval_status: ApprovalStatus = ApprovalStatus.pending
    source_engine_status: str
    created_at: str


# ---------------------------------------------------------------------------
# Water Quality Intelligence models
#
# Advisory, read-only artifacts for the Water Quality Intelligence capability.
# Scaling/fouling/boron risks and forecasts are preliminary engineering
# estimates (never validated production predictions or guaranteed compliance);
# every alert routes through the operator-approval + audit path.
# ---------------------------------------------------------------------------


class SampleType(str, Enum):
    """Whether a sample is a continuous (online analyzer) reading or a lab grab."""

    continuous = "continuous"
    lab = "lab"


class QCStatus(str, Enum):
    """Quality-control disposition of a water-quality sample."""

    passed = "pass"
    warn = "warn"
    fail = "fail"
    pending = "pending"


class WaterQualitySample(BaseModel):
    """A water-quality sample taken at a sampling point.

    ``measurements`` maps a variable name (e.g. ``"boron_mg_l"``) to its value;
    ``method``/``detection_limit`` describe how it was obtained, ``limit`` is the
    applicable advisory compliance limit (when known), and ``qc_status`` records
    the QC disposition. Provenance is ``synthetic`` for generated data.
    """

    sample_id: str
    sampling_point_id: str
    stage: TreatmentStage
    stream_id: Optional[str] = None
    timestamp: str
    provenance: DataProvenance = DataProvenance.synthetic
    measurements: dict[str, float] = Field(default_factory=dict)
    sample_type: SampleType = SampleType.continuous
    method: Optional[str] = None
    detection_limit: Optional[float] = None
    limit: Optional[float] = None
    qc_status: QCStatus = QCStatus.passed


class ContaminantMatrixRow(BaseModel):
    """One contaminant tracked across the treatment path (intake -> brine).

    Concentrations are per stream in the contaminant's native units; fields are
    optional because not every contaminant is measured at every stage. The
    ``removal_pct`` is the intake-to-finished removal percentage.
    """

    contaminant: str
    unit: str
    intake: Optional[float] = None
    post_pretreatment: Optional[float] = None
    ro_feed: Optional[float] = None
    permeate: Optional[float] = None
    finished: Optional[float] = None
    brine: Optional[float] = None
    removal_pct: Optional[float] = None
    limit: Optional[float] = None
    provenance: DataProvenance = DataProvenance.synthetic


class ScalingRisk(BaseModel):
    """Preliminary scaling risk for a scale-forming compound."""

    compound: str
    saturation: float
    probability: float = Field(ge=0, le=1)
    ro_stage_at_risk: Optional[TreatmentStage] = None
    max_safe_recovery: Optional[float] = None
    recommended_antiscalant_note: Optional[str] = None
    provenance: DataProvenance = DataProvenance.preliminary


class WaterQualityForecast(BaseModel):
    """Preliminary physics/trend-based forecast with uncertainty bounds.

    Not a validated production prediction: ``lower``/``upper`` bracket the
    forecast and ``confidence`` is an advisory qualifier only.
    """

    target: str
    unit: str
    horizon: str
    predicted_value: float
    lower: float
    upper: float
    confidence: float = Field(ge=0, le=1)
    basis: Optional[str] = None
    provenance: DataProvenance = DataProvenance.preliminary


class WQAlert(BaseModel):
    """A water-quality alert requiring operator approval before any action."""

    code: str
    stage: Optional[TreatmentStage] = None
    cause: str
    horizon: Optional[str] = None
    confidence: float = Field(ge=0, le=1)
    recommended_action: str
    approval_required: bool = True
    provenance: DataProvenance = DataProvenance.preliminary


# ---------------------------------------------------------------------------
# Equipment & Membrane Intelligence + Predictive Maintenance models
#
# Advisory, read-only artifacts for the Equipment & Membrane Intelligence and
# Predictive Maintenance capabilities. Component health is a transparent
# visible-penalty score; remaining-useful-life, failure probability and
# avoided-cost are PRELIMINARY engineering estimates (never validated or
# guaranteed) and are always stamped ``provenance = preliminary`` with an
# uncertainty band. Every recommendation routes through the operator-approval +
# audit path; nothing here writes to plant controls.
# ---------------------------------------------------------------------------


class ComponentHealth(BaseModel):
    """Transparent 0-100 health for one component with a contribution breakdown.

    Follows the platform's visible-penalty pattern: the score starts at a
    perfect 100 and each labelled :class:`HealthContribution` (a negative
    ``delta``) explains a deduction, so the score is fully auditable.
    """

    asset_id: str
    component_type: str
    score: float = Field(ge=0, le=100)
    band: HealthBand
    contributions: list[HealthContribution] = Field(default_factory=list)
    provenance: DataProvenance = DataProvenance.preliminary


class OperatingEnvelope(BaseModel):
    """Fractions of operating time spent in each envelope regime (0-1 each)."""

    asset_id: str
    samples: int
    at_bep_fraction: float = Field(ge=0, le=1)
    low_flow_fraction: float = Field(ge=0, le=1)
    high_pressure_fraction: float = Field(ge=0, le=1)
    excess_temperature_fraction: float = Field(ge=0, le=1)
    cavitation_risk_fraction: float = Field(ge=0, le=1)
    provenance: DataProvenance = DataProvenance.preliminary


class RemainingUsefulLife(BaseModel):
    """Preliminary remaining-useful-life estimate with an uncertainty band.

    Not a validated or guaranteed time-to-failure: ``lower_days``/``upper_days``
    bracket the point estimate and ``provenance`` is always ``preliminary``.
    """

    asset_id: str
    rul_days: float
    lower_days: float
    upper_days: float
    method: str
    basis: list[str] = Field(default_factory=list)
    provenance: DataProvenance = DataProvenance.preliminary


class FailureProbability(BaseModel):
    """Preliminary failure probability over fixed horizons (monotonic hazard).

    ``horizons`` maps a horizon label (``24h``/``7d``/``30d``/``90d``) to
    ``P(fail before horizon)`` in ``[0, 1]``. Preliminary, not validated.
    """

    asset_id: str
    horizons: dict[str, float] = Field(default_factory=dict)
    predicted_failure_mode: Optional[str] = None
    provenance: DataProvenance = DataProvenance.preliminary


class MaintenancePriority(BaseModel):
    """Maintenance priority rank score (higher = more urgent)."""

    asset_id: str
    rank_score: float
    factors: dict[str, float] = Field(default_factory=dict)
    provenance: DataProvenance = DataProvenance.preliminary


class RootCauseRanking(BaseModel):
    """Ordered candidate root causes whose probabilities sum to ``~1.0``."""

    asset_id: str
    ranked_causes: list[RankedCause] = Field(default_factory=list)
    provenance: DataProvenance = DataProvenance.preliminary


class FoulingSeverity(BaseModel):
    """Membrane fouling/scaling severity components (0-1 each, screening)."""

    organic: float = Field(ge=0, le=1)
    colloidal: float = Field(ge=0, le=1)
    biological: float = Field(ge=0, le=1)
    scaling: float = Field(ge=0, le=1)


class MembraneHealth(BaseModel):
    """Preliminary membrane health derived from normalized WQ signals.

    Reuses the Water Quality layer's normalized indices (permeate-flow decline,
    salt-passage rise, differential-pressure rise) plus fouling/scaling
    severity. ``cleaning_required`` flags a CIP when a normalized threshold is
    crossed. Membrane RUL is a preliminary estimate with an uncertainty band.
    """

    asset_id: str
    score: float = Field(ge=0, le=100)
    band: HealthBand
    normalized_permeate_flow_decline_pct: float
    normalized_salt_passage_rise_pct: float
    normalized_dp_rise_pct: float
    fouling: FoulingSeverity
    salt_passage_trend_pct_per_day: float
    cleaning_required: bool = False
    cleaning_reason: Optional[str] = None
    underperforming_vessel: Optional[str] = None
    rul: Optional[RemainingUsefulLife] = None
    contributions: list[HealthContribution] = Field(default_factory=list)
    provenance: DataProvenance = DataProvenance.preliminary


class PdMRecommendation(BaseModel):
    """A predictive-maintenance recommendation (advisory, approval-gated).

    Bundles the preliminary failure mode, timing and cost estimates for one
    asset. ``time_to_intervention_days``, ``expected_downtime_hours``,
    ``maintenance_cost`` and ``avoided_failure_cost`` are PRELIMINARY estimates,
    never guaranteed figures. The ``control_boundary`` stays read-only and every
    recommendation is created ``pending`` operator approval.
    """

    asset_id: str
    asset_name: Optional[str] = None
    predicted_failure_mode: str
    failure_probability_30d: float = Field(ge=0, le=1)
    rul_days: float
    rul_lower_days: float
    rul_upper_days: float
    time_to_intervention_days: float
    recommended_window: str
    spares_required: list[str] = Field(default_factory=list)
    expected_downtime_hours: float
    maintenance_cost: float
    avoided_failure_cost: float
    rank_score: float
    recommendation_id: Optional[str] = None
    control_boundary: ControlBoundary = Field(default_factory=ControlBoundary)
    approval_status: ApprovalStatus = ApprovalStatus.pending
    provenance: DataProvenance = DataProvenance.preliminary
