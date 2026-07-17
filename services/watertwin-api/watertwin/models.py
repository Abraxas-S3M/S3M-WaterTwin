"""Pydantic models shared across the WaterTwin service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .boundary import ControlBoundary


class Asset(BaseModel):
    """A physical plant asset (pump, membrane train, tank, valve, ...)."""

    id: str
    name: str
    asset_type: str
    location: str
    rated_capacity: float
    unit: str
    status: str = "running"
    installed_year: int


class TelemetryReading(BaseModel):
    """A single point-in-time set of metrics for one asset."""

    asset_id: str
    timestamp: datetime
    metrics: dict[str, float]


class HealthScore(BaseModel):
    asset_id: str
    score: float
    status: str
    factors: dict[str, float] = Field(default_factory=dict)
    computed_at: datetime
    control_boundary: ControlBoundary


class AnomalyResult(BaseModel):
    asset_id: str
    is_anomaly: bool
    score: float
    method: str
    metric: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime
    control_boundary: ControlBoundary


class RecommendationCard(BaseModel):
    id: str
    asset_id: str
    title: str
    summary: str
    rationale: str
    severity: str
    recommended_actions: list[str] = Field(default_factory=list)
    approval_status: str = "pending"
    source: str = "local-fallback"
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    packet: dict[str, Any] = Field(default_factory=dict)
    control_boundary: ControlBoundary


class AuditEvent(BaseModel):
    id: str
    timestamp: datetime
    event_type: str
    actor: str
    subject: str
    details: dict[str, Any] = Field(default_factory=dict)


class PlantSummary(BaseModel):
    scenario: str
    tick_count: int
    asset_count: int
    running: int
    faulted: int
    last_tick: datetime | None = None
    control_boundary: ControlBoundary


class DecisionRequest(BaseModel):
    status: str
    actor: str


class ScenarioRequest(BaseModel):
    scenario: str
"""Core domain models for the WaterTwin RO (reverse-osmosis) digital twin.

These are intentionally dependency-free (standard-library dataclasses and enums)
so the plant seed and synthetic telemetry generator can be exercised without a
database or external services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class AssetType(StrEnum):
    """Kinds of physical assets present in an RO train."""

    PUMP = "pump"
    FILTER = "filter"
    MOTOR = "motor"
    VFD = "vfd"
    ENERGY_RECOVERY_DEVICE = "energy_recovery_device"
    MEMBRANE_ARRAY = "membrane_array"
    CONTROL_VALVE = "control_valve"
    TRANSFORMER = "transformer"
    GENERATOR = "generator"


class Criticality(StrEnum):
    """Business/operational criticality used for risk ranking."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class RatedData:
    """Nameplate / rated operating point for an asset.

    All fields are optional because different asset types expose different
    nameplate data (a transformer has no rated flow, a filter has no rated
    speed, and so on).
    """

    rated_flow_m3h: float | None = None
    rated_pressure_bar: float | None = None
    rated_head_m: float | None = None
    rated_power_kw: float | None = None
    rated_speed_rpm: float | None = None
    rated_voltage_v: float | None = None
    rated_current_a: float | None = None
    rated_efficiency_pct: float | None = None
    rated_temperature_c: float | None = None
    rated_capacity_kva: float | None = None
    notes: str | None = None


@dataclass(frozen=True)
class Asset:
    """A physical asset in the plant (pump, membrane array, transformer, ...)."""

    asset_id: str
    name: str
    asset_type: AssetType
    criticality: Criticality = Criticality.MEDIUM
    parent_id: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    rated_data: RatedData = field(default_factory=RatedData)


@dataclass(frozen=True)
class WaterStream:
    """A process water stream flowing between plant stages."""

    stream_id: str
    name: str
    description: str = ""
    nominal_flow_m3h: float | None = None
    nominal_tds_mg_l: float | None = None
    nominal_pressure_bar: float | None = None


@dataclass(frozen=True)
class SamplingPoint:
    """A location where water-quality / process parameters are sampled."""

    point_id: str
    name: str
    stream_id: str
    stage: str
    parameters: tuple[str, ...] = ()


@dataclass(frozen=True)
class TelemetryReading:
    """A single time-stamped metric value emitted by an asset."""

    asset_id: str
    metric: str
    value: float
    unit: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    provenance: str = "synthetic"
    quality: str = "good"
