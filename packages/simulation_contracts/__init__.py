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
