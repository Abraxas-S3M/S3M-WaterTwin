"""Shared simulation contracts for S3M-WaterTwin what-if services.

Canonical request/result models exchanged between the hydraulic-simulation
service, ``watertwin-api``, and the dashboard. Every simulation is a **read-only
what-if**: results carry ``provenance="simulated"`` and ``status="preliminary"``
and never authorize a control-system write (see :class:`ControlBoundary`).

This package deliberately reuses the shared :class:`ControlBoundary` from
``canonical_water_model`` so the control-boundary contract is identical across
every service and surfaced verbatim on ``/health``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from canonical_water_model import ControlBoundary

__all__ = [
    "ScenarioType",
    "JobState",
    "ViolationSeverity",
    "SimulationRequest",
    "ConstraintViolation",
    "LeakLocalization",
    "ScenarioDelta",
    "SimulationOutputs",
    "SimulationResult",
    "SimulationJob",
    "now_iso",
    "new_job_id",
]

PROVENANCE_SIMULATED = "simulated"
STATUS_PRELIMINARY = "preliminary"


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def new_job_id() -> str:
    """Return a fresh simulation job id."""
    return f"sim-{uuid4().hex[:12]}"


class ScenarioType(str, Enum):
    """Supported read-only what-if scenarios."""

    baseline = "baseline"
    pump_outage = "pump_outage"
    valve_closure = "valve_closure"
    demand_change = "demand_change"
    leak = "leak"


class JobState(str, Enum):
    """Lifecycle state of an async simulation job."""

    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ViolationSeverity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class SimulationRequest(BaseModel):
    """Input to any hydraulic what-if scenario.

    ``parameters`` carries scenario-specific fields, e.g.::

        pump_outage    -> {"pump_id": "PU-PROD-1"}
        valve_closure  -> {"valve_id": "CV-HANDOFF", "setting": 0.0}
        demand_change  -> {"multiplier": 1.25}  or  {"node_demands": {"J-D1": 0.05}}
        leak           -> {"node_id": "J-D2", "area_m2": 0.01, "discharge_coeff": 0.75}
    """

    scenario: ScenarioType = ScenarioType.baseline
    network_id: str = "ro-handoff"
    facility_id: str = "S3M-DESAL-01"
    train_id: str = "RO-TRAIN-001"
    duration_hours: float = Field(default=0.0, ge=0.0)
    parameters: dict[str, Any] = Field(default_factory=dict)
    requested_outputs: list[str] = Field(
        default_factory=lambda: ["pressures", "flows", "tank_levels"]
    )
    notes: Optional[str] = None
    requested_by: Optional[str] = None


class ConstraintViolation(BaseModel):
    """A hydraulic constraint breach detected in a scenario result."""

    element_id: str
    element_type: str  # "node" | "link" | "tank"
    metric: str  # e.g. "pressure_m", "velocity_m_s"
    value: float
    limit: float
    severity: ViolationSeverity = ViolationSeverity.warning
    description: str


class LeakLocalization(BaseModel):
    """Ranked leak-localization result derived from pressure residuals."""

    suspected_node_id: str
    residual_pressure_m: float
    ranked_candidates: list[tuple[str, float]] = Field(default_factory=list)


class ScenarioDelta(BaseModel):
    """Per-element change between baseline and scenario."""

    delivered_flow_baseline_m3h: Optional[float] = None
    delivered_flow_scenario_m3h: Optional[float] = None
    delivered_flow_delta_m3h: Optional[float] = None
    delivered_flow_delta_pct: Optional[float] = None
    pressure_delta_m: dict[str, float] = Field(default_factory=dict)
    flow_delta_m3h: dict[str, float] = Field(default_factory=dict)
    min_pressure_baseline_m: Optional[float] = None
    min_pressure_scenario_m: Optional[float] = None


class SimulationOutputs(BaseModel):
    """Canonical hydraulic outputs (units documented per field)."""

    node_pressure_m: dict[str, float] = Field(default_factory=dict)
    node_head_m: dict[str, float] = Field(default_factory=dict)
    link_flow_m3h: dict[str, float] = Field(default_factory=dict)
    link_velocity_m_s: dict[str, float] = Field(default_factory=dict)
    tank_level_m: dict[str, float] = Field(default_factory=dict)
    delivered_flow_m3h: float = 0.0
    total_demand_m3h: float = 0.0
    total_supply_m3h: float = 0.0
    mass_balance_error_m3h: float = 0.0
    mass_balance_ok: bool = True
    leak_localization: Optional[LeakLocalization] = None
    delta_vs_baseline: Optional[ScenarioDelta] = None


class SimulationResult(BaseModel):
    """Result of a read-only what-if simulation.

    Always ``provenance="simulated"`` and ``status="preliminary"``.
    """

    job_id: str
    status: str = STATUS_PRELIMINARY
    provenance: str = PROVENANCE_SIMULATED
    scenario: ScenarioType
    network_id: str = "ro-handoff"
    engine: str = "EPANET (via WNTR)"
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: SimulationOutputs = Field(default_factory=SimulationOutputs)
    constraint_violations: list[ConstraintViolation] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list)
    control_boundary: ControlBoundary = Field(default_factory=ControlBoundary)
    created_at: str = Field(default_factory=now_iso)
    completed_at: Optional[str] = None

    @property
    def simulation_id(self) -> str:
        """Stable identifier used to attach this run to recommendation evidence."""
        return self.job_id


class SimulationJob(BaseModel):
    """Async job envelope persisted in the shared job store."""

    job_id: str = Field(default_factory=new_job_id)
    scenario: ScenarioType
    state: JobState = JobState.queued
    request: SimulationRequest
    result: Optional[SimulationResult] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    def touch(self) -> "SimulationJob":
        self.updated_at = now_iso()
        return self
