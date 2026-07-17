"""Shared simulation contracts for S3M-WaterTwin what-if services.

Canonical request/result models exchanged between the read-only simulation
services (``services/hydraulic-sim`` and ``services/treatment-sim``),
``watertwin-api``, and the dashboard. Every simulation is a **read-only
what-if / optimization**: results carry ``provenance="simulated"`` and
``status="preliminary"`` and never authorize a control-system write (see
:class:`ControlBoundary`).

Design rules enforced by construction:

* Every simulation artifact is tagged ``provenance="simulated"`` and
  ``status="preliminary"``. Simulated output is *never* labelled measured or
  validated.
* Results are advisory only. The shared :class:`ControlBoundary` is embedded so
  downstream consumers cannot mistake a what-if for a control command.

The single :class:`SimulationJob` envelope is intentionally flexible so the same
contract serves both the hydraulic (EPANET/WNTR) service, which carries a
``scenario`` + :class:`SimulationRequest`, and the treatment (WaterTAP/IDAES)
service, which carries a :class:`SimulationKind` + request payload.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from canonical_water_model import ControlBoundary

__all__ = [
    "now_iso",
    "new_job_id",
    "PROVENANCE_SIMULATED",
    "STATUS_PRELIMINARY",
    "SimulationProvenance",
    "ResultStatus",
    "JobState",
    "SimulationKind",
    "ScenarioType",
    "ViolationSeverity",
    "ControlBoundary",
    # RO (treatment-sim) inputs
    "ROFeed",
    "ROMembrane",
    "ROOperating",
    "SimulateRequest",
    "OptimizeRequest",
    "SensitivitySweep",
    "SensitivityRequest",
    "MembraneDegradationRequest",
    # RO (treatment-sim) results
    "ROBaselineResult",
    "OptimizeResult",
    "SensitivityPoint",
    "SensitivityResult",
    "DegradationResult",
    # Hydraulic (hydraulic-sim) contracts
    "SimulationRequest",
    "ConstraintViolation",
    "LeakLocalization",
    "ScenarioDelta",
    "SimulationOutputs",
    "SimulationResult",
    # Job envelope + service health
    "SimulationJob",
    "HealthResponse",
]

PROVENANCE_SIMULATED = "simulated"
STATUS_PRELIMINARY = "preliminary"


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def new_job_id() -> str:
    """Return a fresh simulation job id."""
    return f"sim-{uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


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


class JobState(str, Enum):
    """Lifecycle state of an async simulation job.

    Superset that serves both simulation services: the hydraulic service uses
    ``completed`` as its terminal success state while the treatment service uses
    ``succeeded``. Both are accepted here so the shared job envelope is portable.
    """

    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    completed = "completed"
    failed = "failed"


class SimulationKind(str, Enum):
    """Which simulation entry-point produced a job (treatment-sim)."""

    simulate = "simulate"
    optimize = "optimize"
    sensitivity = "sensitivity"
    membrane_degradation = "membrane_degradation"


class ScenarioType(str, Enum):
    """Supported read-only hydraulic what-if scenarios (hydraulic-sim)."""

    baseline = "baseline"
    pump_outage = "pump_outage"
    valve_closure = "valve_closure"
    demand_change = "demand_change"
    leak = "leak"


class ViolationSeverity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


# ---------------------------------------------------------------------------
# RO process-simulation request inputs (treatment-sim)
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
# RO process-simulation result payloads (treatment-sim)
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
# Hydraulic what-if contracts (hydraulic-sim)
# ---------------------------------------------------------------------------


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
    """Result of a read-only hydraulic what-if simulation.

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


# ---------------------------------------------------------------------------
# Job envelope + service health (shared)
# ---------------------------------------------------------------------------


class SimulationJob(BaseModel):
    """Async job envelope persisted in the shared job store.

    Flexible enough to serve both simulation services:

    * hydraulic-sim constructs ``SimulationJob(scenario=..., request=<SimulationRequest>)``
      and stores a :class:`SimulationResult` in ``result``;
    * treatment-sim constructs ``SimulationJob(kind=..., request=<dict>, scenario_id=...)``
      and stores an RO result dict in ``result``.

    ``request`` and ``result`` are typed ``Any`` so either a Pydantic model or a
    plain JSON-compatible dict round-trips cleanly.
    """

    job_id: str = Field(default_factory=new_job_id)
    kind: Optional[SimulationKind] = None
    scenario: Optional[ScenarioType] = None
    scenario_id: Optional[str] = None
    state: JobState = JobState.queued
    request: Any = None
    result: Any = None
    error: Optional[str] = None
    engine: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    provenance: SimulationProvenance = SimulationProvenance.simulated
    status: ResultStatus = ResultStatus.preliminary
    control_boundary: ControlBoundary = Field(default_factory=ControlBoundary)

    def touch(self) -> "SimulationJob":
        self.updated_at = now_iso()
        return self


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
