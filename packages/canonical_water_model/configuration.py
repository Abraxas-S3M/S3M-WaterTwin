"""Canonical customer-configuration entity models (shared with analytics).

These are the *content* models for the versioned, approval-gated customer
configuration store. They live in the shared canonical package because analytics
and the engineering layers consume the same configuration a customer publishes
(asset hierarchy, tag mappings, engineering units, rated equipment, pump curves,
membrane models, process stages, sampling points, lab methods, compliance
limits, role assignments).

Only the *content* of each configuration entity is defined here. The versioning
and approval wrapper (draft -> submitted -> approved -> active, audit linkage,
RBAC) is an API/service concern and lives in
``services/watertwin-api/app/configuration``.

Everything here is declarative configuration data. Nothing in this module writes
to any control system; configuration never touches a control path.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from . import AssetType, Criticality, SampleType, StreamType, TreatmentStage

__all__ = [
    "CONFIG_ENTITY_MODELS",
    "config_entity_model",
    "config_entity_types",
    "AssetHierarchyNode",
    "TagDiscoveryStatus",
    "TagDiscoveryRecord",
    "TagMappingConfig",
    "EngineeringUnit",
    "AlarmPriority",
    "AlarmThresholdConfig",
    "RatedEquipmentConfig",
    "PumpCurvePoint",
    "PumpCurveConfig",
    "MembraneModelConfig",
    "ProcessStageConfig",
    "SamplingPointConfig",
    "LabMethodConfig",
    "LimitKind",
    "ComplianceLimitConfig",
    "UserRoleAssignment",
    "KNOWN_ROLES",
]

#: The advisory roles that may be assigned to a user (mirrors ``app.auth.ROLES``).
KNOWN_ROLES: frozenset[str] = frozenset(
    {"viewer", "operator", "engineer", "admin", "auditor"}
)


def _finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


class AssetHierarchyNode(BaseModel):
    """One node in the customer asset hierarchy (parent/child by ``parent_id``)."""

    asset_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    asset_type: AssetType
    facility_id: str = Field(min_length=1)
    train_id: str = Field(min_length=1)
    parent_id: Optional[str] = None
    treatment_stage: Optional[TreatmentStage] = None
    criticality: Criticality = Criticality.medium
    location: Optional[str] = None

    @model_validator(mode="after")
    def _no_self_parent(self) -> "AssetHierarchyNode":
        if self.parent_id is not None and self.parent_id == self.asset_id:
            raise ValueError("asset cannot be its own parent")
        return self


class TagDiscoveryStatus(str, Enum):
    """Lifecycle of a discovered raw OT tag before it is mapped."""

    discovered = "discovered"
    mapped = "mapped"
    ignored = "ignored"


class TagDiscoveryRecord(BaseModel):
    """A raw OT tag observed on a customer source, awaiting mapping.

    Records what was seen on the wire (source, data type, sampled unit, observed
    value range) so an engineer can decide how to map it onto the canonical
    model. Read-only observation only.
    """

    customer_tag: str = Field(min_length=1)
    source: str = Field(min_length=1, description="opcua | modbus | historian | synthetic")
    data_type: Optional[str] = None
    sampled_unit: Optional[str] = None
    address: Optional[str] = Field(default=None, description="NodeId / register / point name")
    observed_min: Optional[float] = None
    observed_max: Optional[float] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    status: TagDiscoveryStatus = TagDiscoveryStatus.discovered

    @model_validator(mode="after")
    def _range_ordered(self) -> "TagDiscoveryRecord":
        lo, hi = self.observed_min, self.observed_max
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("observed_min must be <= observed_max")
        return self


class TagMappingConfig(BaseModel):
    """Map a customer tag onto ``asset_id.metric`` with unit/scale/offset.

    This is the configuration form of a ``data/tag-maps`` entry: canonical value
    is ``raw * scale + offset``. It also carries the engineering unit, the
    sampling frequency and an optional deadband so ingestion tuning is versioned
    alongside the mapping. Consumed by ``app.tag_normalization`` (see
    :meth:`to_tag_map_entry`).
    """

    customer_tag: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    scale: float = 1.0
    offset: float = 0.0
    sampling_frequency_s: float = Field(default=1.0, gt=0)
    deadband: Optional[float] = Field(default=None, ge=0)
    provenance: str = "measured"

    @field_validator("scale")
    @classmethod
    def _scale_nonzero_finite(cls, v: float) -> float:
        _finite(v, "scale")
        if v == 0:
            raise ValueError("scale must be non-zero")
        return v

    @field_validator("offset")
    @classmethod
    def _offset_finite(cls, v: float) -> float:
        return _finite(v, "offset")

    @property
    def target(self) -> str:
        """The canonical ``asset_id.metric`` target for this mapping."""
        return f"{self.asset_id}.{self.metric}"

    def to_tag_map_entry(self) -> dict:
        """Return the ``data/tag-maps`` entry dict for this mapping.

        The result is directly consumable by
        ``app.tag_normalization.TagMap.from_dict`` as the value for
        ``customer_tag``.
        """
        return {
            "asset_id": self.asset_id,
            "metric": self.metric,
            "unit": self.unit,
            "scale": self.scale,
            "offset": self.offset,
        }


class EngineeringUnit(BaseModel):
    """An engineering unit definition with its SI conversion.

    Canonical/SI value is ``value * si_factor + si_offset`` (offset supports
    affine units like degC/degF). ``si_factor`` must be non-zero.
    """

    unit: str = Field(min_length=1)
    quantity_kind: str = Field(min_length=1, description="e.g. temperature, pressure, flow")
    symbol: Optional[str] = None
    si_unit: Optional[str] = None
    si_factor: float = 1.0
    si_offset: float = 0.0
    description: Optional[str] = None

    @field_validator("si_factor")
    @classmethod
    def _factor_nonzero_finite(cls, v: float) -> float:
        _finite(v, "si_factor")
        if v == 0:
            raise ValueError("si_factor must be non-zero")
        return v


class AlarmPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class AlarmThresholdConfig(BaseModel):
    """Alarm limits for one ``asset_id.metric`` (ordered lo_lo<=lo<=hi<=hi_hi)."""

    asset_id: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    unit: Optional[str] = None
    lo_lo: Optional[float] = None
    lo: Optional[float] = None
    hi: Optional[float] = None
    hi_hi: Optional[float] = None
    hysteresis: float = Field(default=0.0, ge=0)
    priority: AlarmPriority = AlarmPriority.medium

    @model_validator(mode="after")
    def _ordered(self) -> "AlarmThresholdConfig":
        # Verify the non-null thresholds are in non-decreasing order.
        ordered = [
            (name, val)
            for name, val in (
                ("lo_lo", self.lo_lo),
                ("lo", self.lo),
                ("hi", self.hi),
                ("hi_hi", self.hi_hi),
            )
            if val is not None
        ]
        if not ordered:
            raise ValueError("at least one alarm threshold must be provided")
        for (n1, v1), (n2, v2) in zip(ordered, ordered[1:]):
            if v1 > v2:
                raise ValueError(f"alarm thresholds out of order: {n1} ({v1}) > {n2} ({v2})")
        return self


class RatedEquipmentConfig(BaseModel):
    """Nameplate / rated data for a piece of equipment (positive magnitudes)."""

    asset_id: str = Field(min_length=1)
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    rated_flow_m3h: Optional[float] = Field(default=None, gt=0)
    rated_head_m: Optional[float] = Field(default=None, gt=0)
    rated_power_kw: Optional[float] = Field(default=None, gt=0)
    rated_speed_rpm: Optional[float] = Field(default=None, gt=0)
    rated_voltage_v: Optional[float] = Field(default=None, gt=0)
    bep_flow_m3h: Optional[float] = Field(default=None, gt=0)
    min_flow_m3h: Optional[float] = Field(default=None, ge=0)
    max_flow_m3h: Optional[float] = Field(default=None, gt=0)
    efficiency_bep: Optional[float] = Field(default=None, gt=0, le=1)
    temp_limit_c: Optional[float] = None
    vibration_limit_mm_s: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _flow_window(self) -> "RatedEquipmentConfig":
        if (
            self.min_flow_m3h is not None
            and self.max_flow_m3h is not None
            and self.min_flow_m3h > self.max_flow_m3h
        ):
            raise ValueError("min_flow_m3h must be <= max_flow_m3h")
        return self


class PumpCurvePoint(BaseModel):
    """A single (flow, head[, efficiency, power]) point on a pump curve."""

    flow_m3h: float = Field(ge=0)
    head_m: float = Field(ge=0)
    efficiency: Optional[float] = Field(default=None, gt=0, le=1)
    power_kw: Optional[float] = Field(default=None, gt=0)


class PumpCurveConfig(BaseModel):
    """A pump performance curve as ordered (flow, head) points.

    Validation ranges: at least two points, flow strictly increasing, head
    non-increasing across the curve (a physical H-Q curve falls as flow rises),
    and every magnitude finite/non-negative.
    """

    asset_id: str = Field(min_length=1)
    name: Optional[str] = None
    speed_rpm: Optional[float] = Field(default=None, gt=0)
    points: list[PumpCurvePoint] = Field(min_length=2)

    @model_validator(mode="after")
    def _monotonic(self) -> "PumpCurveConfig":
        flows = [p.flow_m3h for p in self.points]
        heads = [p.head_m for p in self.points]
        for a, b in zip(flows, flows[1:]):
            if b <= a:
                raise ValueError("pump curve flow_m3h must be strictly increasing")
        for a, b in zip(heads, heads[1:]):
            if b > a:
                raise ValueError("pump curve head_m must be non-increasing as flow rises")
        return self


class MembraneModelConfig(BaseModel):
    """RO/NF membrane element specification with physical validation ranges."""

    model_name: str = Field(min_length=1)
    manufacturer: Optional[str] = None
    element_type: Optional[str] = None
    active_area_m2: float = Field(gt=0)
    permeability_lmh_bar: Optional[float] = Field(default=None, gt=0)
    nominal_salt_rejection_pct: float = Field(gt=0, le=100)
    max_feed_pressure_bar: float = Field(gt=0)
    max_feed_flow_m3h: float = Field(gt=0)
    min_concentrate_flow_m3h: float = Field(gt=0)
    max_recovery: float = Field(gt=0, lt=1)
    max_feed_temperature_c: Optional[float] = Field(default=None, gt=0)
    max_sdi: Optional[float] = Field(default=None, ge=0)
    test_conditions: Optional[str] = None

    model_config = {"protected_namespaces": ()}

    @model_validator(mode="after")
    def _flow_consistency(self) -> "MembraneModelConfig":
        if self.min_concentrate_flow_m3h > self.max_feed_flow_m3h:
            raise ValueError("min_concentrate_flow_m3h must be <= max_feed_flow_m3h")
        return self


class ProcessStageConfig(BaseModel):
    """A treatment process stage in the customer's process definition."""

    stage_id: str = Field(min_length=1)
    treatment_stage: TreatmentStage
    name: str = Field(min_length=1)
    order_index: int = Field(ge=0)
    upstream_stage_id: Optional[str] = None
    stream_type: Optional[StreamType] = None
    description: Optional[str] = None

    @model_validator(mode="after")
    def _no_self_upstream(self) -> "ProcessStageConfig":
        if self.upstream_stage_id is not None and self.upstream_stage_id == self.stage_id:
            raise ValueError("stage cannot be its own upstream stage")
        return self


class SamplingPointConfig(BaseModel):
    """A configured sampling point, its variables and sampling frequency."""

    point_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    stage: TreatmentStage
    stream_id: Optional[str] = None
    location: Optional[str] = None
    sampled_variables: list[str] = Field(default_factory=list)
    sample_type: SampleType = SampleType.continuous
    sampling_frequency_s: Optional[float] = Field(default=None, gt=0)


class LabMethodConfig(BaseModel):
    """A laboratory analytical method for a water-quality analyte."""

    method_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    analyte: str = Field(min_length=1)
    technique: Optional[str] = None
    unit: str = Field(min_length=1)
    detection_limit: Optional[float] = Field(default=None, ge=0)
    precision_pct: Optional[float] = Field(default=None, ge=0)
    standard_reference: Optional[str] = None


class LimitKind(str, Enum):
    """Whether a compliance limit is an upper or lower bound."""

    maximum = "maximum"
    minimum = "minimum"
    range = "range"


class ComplianceLimitConfig(BaseModel):
    """A regulatory / customer compliance limit for an analyte."""

    analyte: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    limit_kind: LimitKind = LimitKind.maximum
    limit_value: Optional[float] = None
    lower_value: Optional[float] = None
    upper_value: Optional[float] = None
    stage: Optional[TreatmentStage] = None
    sampling_point_id: Optional[str] = None
    regulation: Optional[str] = None

    @model_validator(mode="after")
    def _limit_shape(self) -> "ComplianceLimitConfig":
        if self.limit_kind is LimitKind.range:
            if self.lower_value is None or self.upper_value is None:
                raise ValueError("range limit requires lower_value and upper_value")
            if self.lower_value > self.upper_value:
                raise ValueError("lower_value must be <= upper_value")
        else:
            if self.limit_value is None:
                raise ValueError(f"{self.limit_kind.value} limit requires limit_value")
            _finite(self.limit_value, "limit_value")
        return self


class UserRoleAssignment(BaseModel):
    """Assign advisory roles to a user (roles constrained to the known set)."""

    username: str = Field(min_length=1)
    roles: list[str] = Field(min_length=1)
    facility_id: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - KNOWN_ROLES)
        if unknown:
            raise ValueError(f"unknown role(s): {unknown}; known: {sorted(KNOWN_ROLES)}")
        # De-duplicate while preserving order.
        seen: dict[str, None] = {}
        for role in v:
            seen.setdefault(role, None)
        return list(seen)


#: Registry mapping each configuration entity type name to its content model.
#: Shared with analytics so both sides agree on the config entity shapes.
CONFIG_ENTITY_MODELS: dict[str, type[BaseModel]] = {
    "asset": AssetHierarchyNode,
    "tag_discovery": TagDiscoveryRecord,
    "tag_mapping": TagMappingConfig,
    "engineering_unit": EngineeringUnit,
    "alarm_threshold": AlarmThresholdConfig,
    "rated_equipment": RatedEquipmentConfig,
    "pump_curve": PumpCurveConfig,
    "membrane_model": MembraneModelConfig,
    "process_stage": ProcessStageConfig,
    "sampling_point": SamplingPointConfig,
    "lab_method": LabMethodConfig,
    "compliance_limit": ComplianceLimitConfig,
    "user_role_assignment": UserRoleAssignment,
}


def config_entity_types() -> list[str]:
    """Return the sorted list of known configuration entity type names."""
    return sorted(CONFIG_ENTITY_MODELS)


def config_entity_model(entity_type: str) -> type[BaseModel]:
    """Return the content model class for ``entity_type`` (KeyError if unknown)."""
    return CONFIG_ENTITY_MODELS[entity_type]
