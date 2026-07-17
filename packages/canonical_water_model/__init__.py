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
