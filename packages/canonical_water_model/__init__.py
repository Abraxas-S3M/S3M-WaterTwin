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
    "DEFAULT_TENANT_ID",
    "DEFAULT_FACILITY_ID",
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
    "EnergyOptimizationResult",
    "EnergyLoss",
    "ResilienceCriticality",
    "GeneratorStatus",
    "LoadShedItem",
    "LoadShedPlan",
    "ServiceContinuity",
    "ValueComponent",
    "ExecutiveValueSummary",
    "ROIEstimate",
    "DocumentType",
    "DocumentRef",
    "AssistantQuery",
    "AssistantResponse",
    "VALUE_DISCLAIMER",
    "now_iso",
]

#: Canonical default tenant + facility. The platform historically modelled a
#: single seawater-RO facility with no explicit tenant boundary. Multi-tenant
#: scoping treats that pre-existing data as belonging to this default
#: tenant/facility so nothing breaks on upgrade (see the store migration in
#: ``watertwin-api/app/store.py``). ``DEFAULT_FACILITY_ID`` matches the canonical
#: RO facility id used throughout the synthetic plant.
DEFAULT_TENANT_ID = "s3m-default"
DEFAULT_FACILITY_ID = "S3M-DESAL-01"


#: Standard disclaimer stamped on every value/ROI artifact. These figures are
#: illustrative estimates on synthetic pilot data -- not validated savings or
#: guaranteed outcomes.
VALUE_DISCLAIMER = (
    "Illustrative estimates on synthetic pilot data — not validated savings or "
    "guaranteed outcomes. Every figure is preliminary and advisory only."
)


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
    #: Illustrative value/ROI figures derived from synthetic pilot data. NOT a
    #: validated or guaranteed saving/benefit -- always presented with a
    #: disclaimer (used by the energy / resilience / executive value layer).
    estimated = "estimated"
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
    tenant_id: str = DEFAULT_TENANT_ID
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
    tenant_id: str = DEFAULT_TENANT_ID
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
    tenant_id: str = DEFAULT_TENANT_ID
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


# ---------------------------------------------------------------------------
# Value layer: Energy Optimization, Resilience & Generator Command, Executive
# ROI.
#
# Advisory, read-only artifacts for the value layer. Every saving / ROI /
# avoided-cost figure is an ESTIMATED, preliminary number derived from SYNTHETIC
# pilot data -- never a validated saving or a guaranteed outcome. Value figures
# default to ``provenance = estimated`` and executive artifacts carry an explicit
# :data:`VALUE_DISCLAIMER`. Nothing here writes to any control system; resilience
# recommendations route through the operator-approval + audit path.
# ---------------------------------------------------------------------------


class EnergyOptimizationResult(BaseModel):
    """Constrained RO operating-point optimization result (advisory).

    Reports the optimal high-pressure-pump discharge pressure + recovery that
    minimize specific energy consumption (SEC) subject to flow/quality/pressure/
    cavitation/flux constraints, together with baseline-vs-optimized SEC and the
    ESTIMATED energy + cost deltas. The optimizer never violates a constraint;
    ``binding_constraints`` lists any active bounds. Savings are illustrative
    estimates on synthetic data, not validated or guaranteed.
    """

    asset_id: Optional[str] = None
    optimal_feed_pressure_bar: float
    optimal_recovery: float = Field(ge=0, le=1)
    baseline_sec_kwh_m3: float
    optimized_sec_kwh_m3: float
    sec_reduction_kwh_m3: float
    sec_reduction_pct: float
    permeate_flow_m3h: float
    permeate_tds_mg_l: float
    permeate_boron_mg_l: float
    estimated_energy_saving_kwh_day: float
    estimated_cost_saving_per_day: float
    currency: str = "USD"
    constraints_respected: bool = True
    binding_constraints: list[str] = Field(default_factory=list)
    method: str = "scipy.optimize bounded minimize over the deterministic RO model"
    provenance: DataProvenance = DataProvenance.estimated


class EnergyLoss(BaseModel):
    """Avoidable specific-energy loss vs a best-achievable SEC (ESTIMATED)."""

    label: str
    current_sec_kwh_m3: float
    best_achievable_sec_kwh_m3: float
    avoidable_loss_kwh_m3: float
    avoidable_loss_pct: float
    estimated_avoidable_kwh_day: float
    estimated_avoidable_cost_per_day: float
    currency: str = "USD"
    provenance: DataProvenance = DataProvenance.estimated


class ResilienceCriticality(BaseModel):
    """Preliminary resilience-criticality rank score for an asset.

    Higher ``criticality_score`` means the asset is more important to sustain
    under a grid loss (higher impact / failure probability / recovery time /
    dependency centrality / backup deficiency). Preliminary, not validated.
    """

    asset_id: str
    asset_name: Optional[str] = None
    criticality_score: float
    customer_or_production_impact: float = Field(ge=0, le=1)
    failure_probability: float = Field(ge=0, le=1)
    recovery_time_hours: float
    dependency_centrality: float = Field(ge=0, le=1)
    backup_deficiency: float = Field(ge=0, le=1)
    rank: Optional[int] = None
    provenance: DataProvenance = DataProvenance.preliminary


class GeneratorStatus(BaseModel):
    """Preliminary standby-generator readiness + fuel endurance.

    ``start_probability`` is a preliminary reliability estimate in [0, 1] from
    battery state, time since last test and maintenance status. ``fuel_endurance_
    hours`` is how long the generator can carry the current load fraction on its
    remaining fuel. Preliminary, not a guaranteed availability figure.
    """

    generator_id: str
    name: Optional[str] = None
    start_probability: float = Field(ge=0, le=1)
    battery_fraction: float = Field(ge=0, le=1)
    days_since_last_test: float
    maintenance_due: bool = False
    fuel_level_fraction: float = Field(ge=0, le=1)
    consumption_rate_l_per_h: float
    load_fraction: float = Field(ge=0, le=1)
    fuel_endurance_hours: float
    rated_power_kw: Optional[float] = None
    provenance: DataProvenance = DataProvenance.preliminary


class LoadShedItem(BaseModel):
    """One load in the shed plan (retained or shed to protect critical loads)."""

    asset_id: str
    asset_name: Optional[str] = None
    load_kw: float
    priority: str  # "critical" | "essential" | "non_essential"
    shed_order: int  # 1 = shed first; higher = shed later (critical loads last)
    retained: bool


class LoadShedPlan(BaseModel):
    """Preliminary load-shed order to sustain critical loads under limited generation.

    Loads are shed lowest-priority first so the HP pump and essential loads are
    kept last. Preliminary, advisory only -- no control write is issued.
    """

    available_generation_kw: float
    total_load_kw: float
    retained_load_kw: float
    shed_load_kw: float
    items: list[LoadShedItem] = Field(default_factory=list)
    critical_loads_sustained: bool
    provenance: DataProvenance = DataProvenance.preliminary


class ServiceContinuity(BaseModel):
    """Preliminary service-continuity duration under a grid-loss scenario.

    ``service_continuity_hours`` is how long the train can hold product-water
    service under grid loss given generator start probability, fuel endurance
    and the load-shed plan. Preliminary estimate, not a guaranteed duration.
    """

    scenario: str
    service_continuity_hours: float
    limiting_factor: str
    generator_available: bool
    generator_start_probability: float = Field(ge=0, le=1)
    fuel_endurance_hours: float
    battery_bridge_minutes: float
    critical_loads_sustained: bool
    provenance: DataProvenance = DataProvenance.preliminary


class ValueComponent(BaseModel):
    """One ESTIMATED benefit component aggregated into the executive summary."""

    category: str
    annualized_benefit: float
    basis: str
    currency: str = "USD"
    provenance: DataProvenance = DataProvenance.estimated


class ExecutiveValueSummary(BaseModel):
    """Aggregated ESTIMATED benefits across the platform layers (illustrative).

    Aggregates estimated benefits from existing layers (downtime avoided, energy
    savings, chemical savings, water-loss avoided, maintenance savings, capex
    deferred). CRITICAL HONESTY: every figure is an ESTIMATED, preliminary number
    derived from SYNTHETIC pilot data -- not a validated saving or guaranteed
    outcome. The ``disclaimer`` must be surfaced wherever these figures appear.
    """

    facility_id: str
    train_id: str
    currency: str = "USD"
    downtime_avoided: float
    energy_savings: float
    chemical_savings: float
    water_loss_avoided: float
    maintenance_savings: float
    capex_deferred: float
    total_annualized_benefit: float
    components: list[ValueComponent] = Field(default_factory=list)
    synthetic_basis: bool = True
    disclaimer: str = VALUE_DISCLAIMER
    provenance: DataProvenance = DataProvenance.estimated


class ROIEstimate(BaseModel):
    """Illustrative pilot ROI, annualized benefit and payback (ESTIMATED).

    CRITICAL HONESTY: derived from SYNTHETIC pilot data; not validated ROI or a
    guaranteed payback. The ``disclaimer`` must be surfaced wherever it appears.
    """

    facility_id: str
    train_id: str
    currency: str = "USD"
    pilot_investment: float
    pilot_benefit: float
    pilot_roi_pct: float
    annualized_benefit: float
    payback_period_months: float
    synthetic_basis: bool = True
    disclaimer: str = VALUE_DISCLAIMER
    provenance: DataProvenance = DataProvenance.estimated


# ---------------------------------------------------------------------------
# S3M Operations Assistant models
#
# Advisory, read-only artifacts for the grounded natural-language operations
# assistant. The assistant AGGREGATES the outputs the platform already computes
# (health / anomaly / root-cause / water-quality / equipment / membrane / PdM /
# energy / resilience / executive) plus retrieved seeded documents; it never
# answers operational questions from general model knowledge. Every
# :class:`AssistantResponse` carries the read-only control boundary and a full
# :class:`Evidence` block naming exactly what was reviewed, so an operator can
# always see the platform data + documents behind an answer. Any recommended
# action is a ``pending`` :class:`RecommendationCard` (operator approval
# required, no control write).
# ---------------------------------------------------------------------------


class DocumentType(str, Enum):
    """Class of a seeded operations document."""

    manual = "manual"
    procedure = "procedure"
    maintenance_record = "maintenance_record"


class DocumentRef(BaseModel):
    """A reference to a retrieved operations document (not its full body).

    ``score`` is the keyword-retrieval relevance score (higher = more relevant);
    ``snippet`` is a short excerpt for display. Semantic / pgvector retrieval is
    a later hardening upgrade -- retrieval is honest keyword matching for now.
    """

    document_id: str
    title: str
    document_type: DocumentType
    path: str
    tags: list[str] = Field(default_factory=list)
    score: Optional[float] = None
    snippet: Optional[str] = None


class AssistantQuery(BaseModel):
    """An operator question submitted to the operations assistant."""

    question: str = Field(min_length=1, max_length=1000)
    requested_by: Optional[str] = None


class AssistantResponse(BaseModel):
    """A grounded, evidence-backed answer from the operations assistant.

    The ``answer`` is assembled from platform layer outputs + retrieved
    documents (never from general model knowledge). ``evidence`` names the data
    timestamp, assets reviewed, documents reviewed, simulations used and
    assumptions behind the answer. ``recommended_action`` (when present) is a
    ``pending`` recommendation routed through the existing approval + audit path.
    ``source_engine_status`` records whether the S3M-Core quad-engine produced
    the orchestration or a grounded local fallback was used
    (``"fallback_local"``).
    """

    query: str
    intent: str
    target: Optional[str] = None
    answer: str
    evidence: Evidence
    confidence: float = Field(ge=0, le=1)
    recommended_action: Optional[RecommendationCard] = None
    approval_required: bool = True
    grounded: bool = True
    source_engine_status: str
    provenance: DataProvenance = DataProvenance.preliminary
    control_boundary: ControlBoundary = Field(default_factory=ControlBoundary)
    packet_id: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
