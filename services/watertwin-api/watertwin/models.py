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
