"""Shared contracts for S3M-WaterTwin process-simulation services.

This package defines the request/result data models and job envelope that the
read-only process-simulation services (e.g. ``services/treatment-sim``) expose
and that the API layer consumes. It is engine-agnostic: the same contracts are
used whether a result is produced by the WaterTAP/IDAES stack or an analytical
reference model.

Design rules that these contracts enforce by construction:

* Every simulation result carries ``provenance = "simulated"`` and
  ``status = "preliminary"``. Simulated output is *never* labelled as measured
  or validated.
* Results are advisory only. The :class:`ControlBoundary` block is embedded so
  downstream consumers cannot mistake a what-if for a control command.

The enums intentionally mirror ``canonical_water_model`` (``DataProvenance``,
``ControlBoundary``) so the two packages stay aligned, while keeping this
package importable on its own.
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
from typing import Optional

from pydantic import BaseModel, Field

__all__ = [
    "now_iso",
    "SimulationProvenance",
    "ResultStatus",
    "JobState",
    "SimulationKind",
    "ControlBoundary",
    "ROFeed",
    "ROMembrane",
    "ROOperating",
    "SimulateRequest",
    "OptimizeRequest",
    "SensitivitySweep",
    "SensitivityRequest",
    "MembraneDegradationRequest",
    "ROBaselineResult",
    "OptimizeResult",
    "SensitivityPoint",
    "SensitivityResult",
    "DegradationResult",
    "SimulationJob",
    "HealthResponse",
]

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


class SimulationProvenance(str, Enum):
    """Provenance label for every simulated artifact.

    A process simulation is neither ``measured`` nor ``synthetic`` telemetry;
    it is a model output and must always be tagged as ``simulated``.
    """

    simulated = "simulated"


class ResultStatus(str, Enum):
    """Maturity of a simulation result.

    Simulated results are always ``preliminary`` until validated against
    measured plant data by an operator; the service never emits ``validated``.
    """

    preliminary = "preliminary"
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
    succeeded = "succeeded"
    failed = "failed"


class SimulationKind(str, Enum):
    """Which simulation entry-point produced a job."""

    simulate = "simulate"
    optimize = "optimize"
    sensitivity = "sensitivity"
    membrane_degradation = "membrane_degradation"


class ControlBoundary(BaseModel):
    """Advisory-only guardrail carried by every simulation artifact.

    Mirrors ``canonical_water_model.ControlBoundary``. Simulation is strictly
    read-only what-if / optimization; there is no closed-loop control path.
    """

    control_mode: str = "advisory"
    operator_approval_required: bool = True
    control_write_enabled: bool = False


# ---------------------------------------------------------------------------
# Request inputs
# ---------------------------------------------------------------------------


class ROFeed(BaseModel):
    """Reverse-osmosis feed-water specification."""

    flow_m3h: float = Field(gt=0, description="Feed volumetric flow (m3/h).")
    tds_mg_l: float = Field(
        gt=0, description="Feed total dissolved solids as NaCl-equivalent (mg/L)."
    )
    temperature_c: float = Field(
        default=25.0, gt=0, lt=100, description="Feed temperature (deg C)."
    )
    pressure_bar: float = Field(
        gt=0, description="Applied feed (high-pressure pump) pressure (bar)."
    )


class ROMembrane(BaseModel):
    """Reverse-osmosis membrane element / array specification.

    ``a_lmh_bar`` and ``b_lmh`` are the solution-diffusion water (A) and salt
    (B) permeability coefficients.
    """

    area_m2: float = Field(gt=0, description="Total active membrane area (m2).")
    a_lmh_bar: float = Field(
        default=3.0,
        gt=0,
        description="Water permeability coefficient A (L/m2/h/bar, LMH/bar).",
    )
    b_lmh: float = Field(
        default=0.15,
        gt=0,
        description="Salt permeability coefficient B (L/m2/h, LMH).",
    )


class ROOperating(BaseModel):
    """Operating / equipment efficiencies used for the energy balance."""

    pump_efficiency: float = Field(default=0.8, gt=0, le=1)
    erd_efficiency: float = Field(
        default=0.95,
        ge=0,
        le=1,
        description="Energy-recovery-device efficiency (0 disables ERD).",
    )
    use_erd: bool = Field(default=True)
    pressure_drop_bar: float = Field(
        default=1.0, ge=0, description="Feed-channel pressure drop (bar)."
    )


class SimulateRequest(BaseModel):
    """Baseline RO simulation request."""

    feed: ROFeed
    membrane: ROMembrane
    operating: ROOperating = Field(default_factory=ROOperating)
    scenario_id: Optional[str] = None
    notes: Optional[str] = None


class OptimizeRequest(BaseModel):
    """Minimize specific energy subject to recovery + product-quality limits."""

    feed: ROFeed
    membrane: ROMembrane
    operating: ROOperating = Field(default_factory=ROOperating)
    min_recovery: float = Field(
        default=0.40, gt=0, lt=1, description="Required minimum permeate recovery."
    )
    max_permeate_tds_mg_l: float = Field(
        default=500.0, gt=0, description="Product-quality limit on permeate TDS."
    )
    pressure_bounds_bar: tuple[float, float] = Field(
        default=(20.0, 82.0),
        description="Search bounds for applied pressure (bar).",
    )
    scenario_id: Optional[str] = None


class SensitivitySweep(BaseModel):
    """Definition of a single-variable sweep."""

    variable: str = Field(
        description="One of: feed_tds_mg_l, feed_temperature_c, feed_pressure_bar."
    )
    start: float
    stop: float
    steps: int = Field(default=5, ge=2, le=50)


class SensitivityRequest(BaseModel):
    """Sweep feed salinity / temperature / pressure and report the response."""

    feed: ROFeed
    membrane: ROMembrane
    operating: ROOperating = Field(default_factory=ROOperating)
    sweep: SensitivitySweep
    scenario_id: Optional[str] = None


class MembraneDegradationRequest(BaseModel):
    """Apply an A/B permeability decline and report the impact.

    ``a_retention`` and ``b_increase`` are multiplicative factors applied to the
    baseline permeability coefficients: ``A_aged = A0 * a_retention`` (water
    permeability declines, so < 1) and ``B_aged = B0 * b_increase`` (salt
    passage increases, so > 1).
    """

    feed: ROFeed
    membrane: ROMembrane
    operating: ROOperating = Field(default_factory=ROOperating)
    a_retention: float = Field(
        default=0.85, gt=0, le=1, description="Fraction of A retained after aging."
    )
    b_increase: float = Field(
        default=1.5, ge=1, description="Multiplier on salt permeability B."
    )
    scenario_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Result payloads
# ---------------------------------------------------------------------------


class ROBaselineResult(BaseModel):
    """Baseline RO performance metrics."""

    recovery: float = Field(description="Permeate recovery fraction Qp/Qf.")
    permeate_flow_m3h: float
    concentrate_flow_m3h: float
    permeate_tds_mg_l: float
    concentrate_tds_mg_l: float
    salt_rejection: float = Field(description="Observed salt rejection fraction.")
    specific_energy_kwh_m3: float
    net_driving_pressure_bar: float
    feed_osmotic_pressure_bar: float
    water_flux_lmh: float
    engine: str = Field(description="watertap | analytical")
    provenance: SimulationProvenance = SimulationProvenance.simulated
    status: ResultStatus = ResultStatus.preliminary


class OptimizeResult(BaseModel):
    optimal_pressure_bar: float
    baseline: ROBaselineResult
    feasible: bool
    objective_specific_energy_kwh_m3: float
    constraints_report: dict = Field(default_factory=dict)
    engine: str
    provenance: SimulationProvenance = SimulationProvenance.simulated
    status: ResultStatus = ResultStatus.preliminary


class SensitivityPoint(BaseModel):
    value: float
    result: ROBaselineResult


class SensitivityResult(BaseModel):
    variable: str
    points: list[SensitivityPoint] = Field(default_factory=list)
    engine: str
    provenance: SimulationProvenance = SimulationProvenance.simulated
    status: ResultStatus = ResultStatus.preliminary


class DegradationResult(BaseModel):
    baseline: ROBaselineResult
    aged: ROBaselineResult
    normalized_permeate_flow: float = Field(
        description="Aged permeate flow / baseline permeate flow."
    )
    permeate_tds_change_mg_l: float
    specific_energy_change_kwh_m3: float
    engine: str
    provenance: SimulationProvenance = SimulationProvenance.simulated
    status: ResultStatus = ResultStatus.preliminary


# ---------------------------------------------------------------------------
# Job envelope + service health
# ---------------------------------------------------------------------------


class SimulationJob(BaseModel):
    """Async job envelope returned by the simulation endpoints."""

    job_id: str
    kind: SimulationKind
    state: JobState = JobState.queued
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    request: dict = Field(default_factory=dict)
    result: Optional[dict] = None
    error: Optional[str] = None
    engine: Optional[str] = None
    scenario_id: Optional[str] = None
    provenance: SimulationProvenance = SimulationProvenance.simulated
    status: ResultStatus = ResultStatus.preliminary
    control_boundary: ControlBoundary = Field(default_factory=ControlBoundary)


class HealthResponse(BaseModel):
    """Service health with control-boundary fields."""

    status: str = "ok"
    service: str = "treatment-sim"
    engine: str
    watertap_available: bool
    solver_available: bool
    control_mode: str = "advisory"
    operator_approval_required: bool = True
    control_write_enabled: bool = False
    version: str = "0.1.0"
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
