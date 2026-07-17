"""Operator Training Simulator engine (SIMULATION, sandboxed, read-only).

A guided operator-training capability built entirely on the platform's *existing*
replayable synthetic telemetry + scenario engine. It lets an operator rehearse
their response to a fault without any risk to the plant:

1. **Inject a scenario** — one of the reference drills (pump degradation, leak,
   outage, storm / power loss). The injected twin snapshot is derived from the
   same synthetic telemetry the platform already generates
   (:data:`app.predictive_maintenance.ASSETS`) and the same read-only scenario
   engines (the hydraulic what-if :class:`simulation_contracts.ScenarioType` and
   the resilience grid-outage assessment). Every value is
   ``provenance = "simulated"``.
2. **Diagnose using the twin** — the operator inspects the (simulated) symptoms.
3. **Capture actions / approvals** — the operator's diagnosis, chosen actions and
   approvals are recorded in a :class:`TrainingSandbox`.
4. **Score against a rubric** — the captured actions are scored against an
   expected-response rubric and a durable :class:`TrainingRecord` is produced.

Hard safety boundary (non-negotiable, enforced in code + tests):

* This is a **SIMULATION**. Nothing here touches a real plant.
* The :class:`TrainingSandbox` **cannot emit any command**. There is no control
  path, no OT connector, no PLC/SCADA/VFD/valve/pump write, and no
  recommendation-approval side effect. ``control_write_enabled`` is always
  ``False`` and any attempt to emit a command raises
  :class:`SandboxViolationError`.

Nothing in this module writes to any control system.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from canonical_water_model import (
    ControlBoundary,
    DataProvenance,
    TelemetryReading,
    now_iso,
)
from simulation_contracts import ScenarioType

from . import predictive_maintenance as pdm
from . import resilience as resil
from .sources.synthetic import unit_for

#: Mandatory label surfaced on every training artifact. Training is a simulation
#: rehearsal only -- it is never a live control action or a validated outcome.
TRAINING_DISCLAIMER = (
    "SIMULATION — operator training drill on synthetic data. This is a sandboxed "
    "rehearsal only: no real control action is taken, no command is emitted, and "
    "nothing reaches any plant, OT, PLC or SCADA system. Scores are training "
    "feedback, not a validated assessment."
)

#: Passing threshold (percentage) for a drill.
PASS_THRESHOLD_PCT = 70.0


class SandboxViolationError(RuntimeError):
    """Raised if anything attempts to emit a command from the training sandbox.

    The training sandbox has no control-write path by construction; this error
    exists so the isolation guarantee is explicit and testable.
    """


class TrainingScenarioType(str, Enum):
    """The reference operator-training drills."""

    pump_degradation = "pump_degradation"
    leak = "leak"
    outage = "outage"
    storm_power_loss = "storm_power_loss"


# --------------------------------------------------------------------------- #
# Models (advisory, simulation-only artifacts)
# --------------------------------------------------------------------------- #


class RubricItem(BaseModel):
    """One expected-response item the operator is scored against.

    ``keywords`` are matched (case-insensitively) against the operator's captured
    actions; they are internal scoring detail and are not echoed back to the
    trainee, so the drill remains a genuine assessment.
    """

    key: str
    prompt: str
    guidance: str
    weight: float = Field(gt=0)
    #: Excluded from serialization so the exact match list is never revealed to
    #: the trainee; still available server-side for deterministic scoring.
    keywords: list[str] = Field(default_factory=list, exclude=True)


class TrainingScenario(BaseModel):
    """A guided drill: briefing, injected-fault description and scoring rubric."""

    scenario_id: str
    scenario_type: TrainingScenarioType
    title: str
    category: str
    difficulty: str
    briefing: str
    #: The read-only engine the injected twin snapshot is derived from (honesty
    #: about reuse of the existing scenario engine).
    derived_from: str
    learning_objectives: list[str] = Field(default_factory=list)
    rubric: list[RubricItem] = Field(default_factory=list)


class CapturedAction(BaseModel):
    """An operator action captured in the sandbox (recorded for scoring only).

    ``sandboxed`` is always ``True`` and ``emitted_command`` is always ``False``:
    a captured action never becomes a control command.
    """

    action_id: str
    kind: str  # "diagnosis" | "action" | "approval" | "note"
    text: str
    rubric_key: Optional[str] = None
    approved: Optional[bool] = None
    sandboxed: bool = True
    emitted_command: bool = False
    recorded_at: str = Field(default_factory=now_iso)


class ScoredItem(BaseModel):
    """Per-rubric-item scoring outcome."""

    key: str
    prompt: str
    weight: float
    matched: bool
    awarded: float
    feedback: str


class TrainingScore(BaseModel):
    """Aggregate score of a drill against its rubric (training feedback only)."""

    total_score: float = Field(ge=0, le=100)
    max_score: float
    percentage: float = Field(ge=0, le=100)
    band: str
    passed: bool
    items: list[ScoredItem] = Field(default_factory=list)
    provenance: DataProvenance = DataProvenance.simulated


class TrainingSession(BaseModel):
    """An in-progress drill: the injected simulated twin snapshot + captured actions."""

    session_id: str
    scenario_id: str
    scenario: TrainingScenario
    operator: str
    status: str = "in_progress"  # "in_progress" | "scored"
    simulation: bool = True
    twin_summary: dict = Field(default_factory=dict)
    injected_telemetry: list[TelemetryReading] = Field(default_factory=list)
    actions: list[CapturedAction] = Field(default_factory=list)
    started_at: str = Field(default_factory=now_iso)
    provenance: DataProvenance = DataProvenance.simulated
    control_boundary: ControlBoundary = Field(default_factory=ControlBoundary)
    disclaimer: str = TRAINING_DISCLAIMER


class TrainingRecord(BaseModel):
    """A durable training record produced when a drill is scored (simulation only)."""

    record_id: str
    session_id: str
    scenario_id: str
    scenario_title: str
    operator: str
    score: TrainingScore
    actions: list[CapturedAction] = Field(default_factory=list)
    started_at: str
    completed_at: str = Field(default_factory=now_iso)
    simulation: bool = True
    provenance: DataProvenance = DataProvenance.simulated
    control_boundary: ControlBoundary = Field(default_factory=ControlBoundary)
    disclaimer: str = TRAINING_DISCLAIMER


# --------------------------------------------------------------------------- #
# Sandbox: captures operator actions; CANNOT emit any command.
# --------------------------------------------------------------------------- #


class TrainingSandbox:
    """Captures operator actions for a training drill. Cannot emit any command.

    The sandbox is deliberately isolated: it holds captured actions in memory for
    scoring and has **no** reference to any control system, OT connector, or
    recommendation-approval path. ``control_write_enabled`` is a hard ``False``
    and :meth:`emit_command` always raises :class:`SandboxViolationError`, so the
    "no command can be emitted" guarantee is explicit and testable.
    """

    #: Static isolation invariants (mirrors the platform control boundary).
    is_simulation: bool = True
    control_write_enabled: bool = False
    can_emit_command: bool = False

    def __init__(self) -> None:
        self._actions: list[CapturedAction] = []

    @property
    def actions(self) -> list[CapturedAction]:
        return list(self._actions)

    def record_action(
        self,
        kind: str,
        text: str,
        rubric_key: Optional[str] = None,
        approved: Optional[bool] = None,
    ) -> CapturedAction:
        """Record an operator action for scoring. Never emits a control command."""
        action = CapturedAction(
            action_id=f"act-{uuid4().hex[:12]}",
            kind=kind,
            text=text,
            rubric_key=rubric_key,
            approved=approved,
            sandboxed=True,
            emitted_command=False,
        )
        self._actions.append(action)
        return action

    def emit_command(self, *_args, **_kwargs) -> None:
        """Always refuse: the training sandbox has no control-write path.

        Present only so the isolation guarantee is explicit and testable; calling
        it never reaches any plant, OT, PLC or SCADA system.
        """
        raise SandboxViolationError(
            "training sandbox cannot emit commands: no control-write path exists "
            "(this is a simulation)"
        )


# --------------------------------------------------------------------------- #
# Scenario catalog (reuses the existing synthetic telemetry + scenario engines)
# --------------------------------------------------------------------------- #


def _reading(asset_id: str, metric: str, value: float, *, unit: Optional[str] = None) -> TelemetryReading:
    """Build one simulated telemetry reading for the injected twin snapshot."""
    return TelemetryReading(
        asset_id=asset_id,
        metric=metric,
        value=float(value),
        unit=unit or unit_for(metric),
        timestamp=now_iso(),
        provenance=DataProvenance.simulated,
    )


def _pump_degradation_injection() -> tuple[list[TelemetryReading], dict]:
    """Pump-degradation drill: reuse the synthetic HP-pump degradation telemetry."""
    spec = pdm.ASSETS["AST-HPP-01"]
    readings = [
        _reading("AST-HPP-01", metric, value) for metric, value in spec.telemetry.items()
    ]
    summary = {
        "headline": "High-Pressure Pump A: rising vibration and bearing temperature "
        "with a falling efficiency trend.",
        "observed": {
            "vibration_mm_s": spec.telemetry.get("vibration_mm_s"),
            "vibration_limit_mm_s": spec.telemetry.get("vibration_limit_mm_s"),
            "bearing_temp_c": spec.telemetry.get("bearing_temp_c"),
            "bearing_temp_limit_c": spec.telemetry.get("bearing_temp_limit_c"),
            "efficiency_drift_pct": spec.telemetry.get("efficiency_drift_pct"),
        },
        "affected_asset": "AST-HPP-01",
        "reused_scenario": ScenarioType.pump_outage.value,
    }
    return readings, summary


def _leak_injection() -> tuple[list[TelemetryReading], dict]:
    """Leak drill: reuse the hydraulic ``leak`` what-if signature (product-water side)."""
    readings = [
        _reading("NODE-J-D2", "pressure_bar", 1.9),
        _reading("NODE-J-D2", "baseline_pressure_bar", 3.4),
        _reading("AST-BOOST-01", "discharge_flow_m3h", 512.0),
        _reading("MTR-PRODUCT-01", "delivered_flow_m3h", 441.0),
        _reading("MTR-PRODUCT-01", "baseline_delivered_flow_m3h", 498.0),
    ]
    summary = {
        "headline": "Product-water handoff: unaccounted flow with a pressure drop at "
        "node J-D2 — a probable leak.",
        "observed": {
            "delivered_flow_m3h": 441.0,
            "baseline_delivered_flow_m3h": 498.0,
            "unaccounted_flow_m3h": 57.0,
            "node_pressure_bar": 1.9,
        },
        "affected_asset": "NODE-J-D2",
        "reused_scenario": ScenarioType.leak.value,
    }
    return readings, summary


def _outage_injection() -> tuple[list[TelemetryReading], dict]:
    """Outage drill: reuse the resilience grid-outage assessment."""
    assessment = resil.assess_grid_outage()
    gen = assessment["generator"]
    continuity = assessment["service_continuity"]
    readings = [
        _reading("BUS-MV-01", "grid_voltage_pct", 0.0),
        _reading("GEN-001", "start_probability_pct", round(gen.start_probability * 100, 1)),
        _reading("GEN-001", "fuel_level_pct", round(gen.fuel_level_fraction * 100, 1)),
        _reading("GEN-001", "fuel_endurance_h", round(gen.fuel_endurance_hours, 1)),
        _reading(
            "RO-TRAIN-001",
            "service_continuity_h",
            round(continuity.service_continuity_hours, 1),
        ),
    ]
    summary = {
        "headline": "Total grid loss on the MV bus. Standby generator must carry the "
        "critical loads; non-essential loads should be shed.",
        "observed": {
            "grid_voltage_pct": 0.0,
            "generator_start_probability": gen.start_probability,
            "fuel_endurance_hours": gen.fuel_endurance_hours,
            "service_continuity_hours": continuity.service_continuity_hours,
            "critical_loads_sustained": continuity.critical_loads_sustained,
        },
        "affected_asset": "BUS-MV-01",
        "reused_scenario": "grid_outage",
    }
    return readings, summary


def _storm_power_loss_injection() -> tuple[list[TelemetryReading], dict]:
    """Storm / power-loss drill: resilience grid-outage under a storm context."""
    assessment = resil.assess_grid_outage(fuel_level_fraction=0.45)
    gen = assessment["generator"]
    continuity = assessment["service_continuity"]
    readings = [
        _reading("MET-01", "wind_speed_kmh", 96.0),
        _reading("BUS-MV-01", "grid_voltage_pct", 0.0),
        _reading("AST-INTAKE-01", "turbidity_ntu", 18.5),
        _reading("GEN-001", "fuel_level_pct", round(gen.fuel_level_fraction * 100, 1)),
        _reading(
            "RO-TRAIN-001",
            "service_continuity_h",
            round(continuity.service_continuity_hours, 1),
        ),
    ]
    summary = {
        "headline": "Storm front: grid lost, feedwater turbidity spiking and generator "
        "fuel is limited. Protect the membranes and sustain critical loads.",
        "observed": {
            "wind_speed_kmh": 96.0,
            "grid_voltage_pct": 0.0,
            "intake_turbidity_ntu": 18.5,
            "generator_fuel_level_pct": round(gen.fuel_level_fraction * 100, 1),
            "service_continuity_hours": continuity.service_continuity_hours,
        },
        "affected_asset": "RO-TRAIN-001",
        "reused_scenario": "grid_outage",
    }
    return readings, summary


_INJECTORS = {
    TrainingScenarioType.pump_degradation: _pump_degradation_injection,
    TrainingScenarioType.leak: _leak_injection,
    TrainingScenarioType.outage: _outage_injection,
    TrainingScenarioType.storm_power_loss: _storm_power_loss_injection,
}


_SCENARIOS: dict[str, TrainingScenario] = {
    "pump-degradation": TrainingScenario(
        scenario_id="pump-degradation",
        scenario_type=TrainingScenarioType.pump_degradation,
        title="High-Pressure Pump Degradation",
        category="Rotating equipment",
        difficulty="foundational",
        briefing=(
            "During your shift the high-pressure feed pump (AST-HPP-01) shows a "
            "rising vibration trend, a bearing temperature approaching its alarm "
            "limit and a falling efficiency trend. Diagnose the developing fault "
            "using the twin and decide on the correct advisory response."
        ),
        derived_from="synthetic PdM telemetry (AST-HPP-01) + hydraulic pump_outage what-if",
        learning_objectives=[
            "Recognise a progressive rotating-equipment degradation from telemetry.",
            "Prioritise a vibration diagnostic and bearing inspection.",
            "Plan intervention in a low-demand window without an unplanned trip.",
        ],
        rubric=[
            RubricItem(
                key="diagnose_vibration",
                prompt="Identify the rising vibration / bearing-wear signature.",
                guidance="Call out the vibration trend against the ISO alarm limit.",
                weight=2.0,
                keywords=["vibration", "bearing", "wear", "imbalance"],
            ),
            RubricItem(
                key="efficiency_loss",
                prompt="Note the hydraulic-efficiency drift.",
                guidance="Reference the falling efficiency / performance trend.",
                weight=1.0,
                keywords=["efficiency", "performance", "drift", "degradation"],
            ),
            RubricItem(
                key="plan_maintenance",
                prompt="Schedule a diagnostic / maintenance in a low-demand window.",
                guidance="Plan an inspection rather than tripping the pump immediately.",
                weight=2.0,
                keywords=["schedule", "maintenance", "inspect", "diagnostic", "plan", "window"],
            ),
            RubricItem(
                key="advisory_only",
                prompt="Keep the response advisory (operator approval, no control write).",
                guidance="Confirm no automatic control action; approval is required.",
                weight=1.0,
                keywords=["advisory", "approval", "no control", "operator", "recommend"],
            ),
        ],
    ),
    "leak": TrainingScenario(
        scenario_id="leak",
        scenario_type=TrainingScenarioType.leak,
        title="Product-Water Leak",
        category="Hydraulics",
        difficulty="intermediate",
        briefing=(
            "Delivered product-water flow has dropped while feed flow held steady, "
            "and pressure at distribution node J-D2 has fallen. Water is "
            "unaccounted for. Diagnose the probable leak and decide the response."
        ),
        derived_from="hydraulic leak what-if (simulation_contracts.ScenarioType.leak)",
        learning_objectives=[
            "Detect a leak from a flow / pressure imbalance.",
            "Localise the affected node from the twin.",
            "Dispatch isolation / inspection while protecting supply continuity.",
        ],
        rubric=[
            RubricItem(
                key="detect_leak",
                prompt="Identify the unaccounted-flow / pressure-drop leak signature.",
                guidance="Compare delivered vs feed flow and the node pressure drop.",
                weight=2.0,
                keywords=["leak", "unaccounted", "loss", "pressure drop", "imbalance"],
            ),
            RubricItem(
                key="localise",
                prompt="Localise the leak to node J-D2.",
                guidance="Name the low-pressure node from the twin.",
                weight=1.5,
                keywords=["j-d2", "node", "localis", "localiz", "district", "segment"],
            ),
            RubricItem(
                key="dispatch_inspection",
                prompt="Dispatch isolation / field inspection of the segment.",
                guidance="Send a crew / isolate the segment to confirm and stop the loss.",
                weight=2.0,
                keywords=["isolate", "inspect", "dispatch", "crew", "valve", "repair"],
            ),
            RubricItem(
                key="advisory_only",
                prompt="Keep the response advisory (operator approval, no control write).",
                guidance="Confirm no automatic valve operation; approval is required.",
                weight=1.0,
                keywords=["advisory", "approval", "no control", "operator", "recommend"],
            ),
        ],
    ),
    "outage": TrainingScenario(
        scenario_id="outage",
        scenario_type=TrainingScenarioType.outage,
        title="Grid Outage",
        category="Power & resilience",
        difficulty="intermediate",
        briefing=(
            "The medium-voltage bus has lost grid power. The standby generator must "
            "pick up the critical loads. Diagnose the situation and decide the "
            "load-shed and generator-priority response."
        ),
        derived_from="resilience grid-outage assessment (app.resilience.assess_grid_outage)",
        learning_objectives=[
            "Confirm generator start and readiness.",
            "Prioritise the HP pump + essential loads and shed non-essential loads.",
            "Track service-continuity duration against fuel endurance.",
        ],
        rubric=[
            RubricItem(
                key="confirm_generator",
                prompt="Confirm the standby generator has started / is available.",
                guidance="Verify generator start probability and fuel level.",
                weight=1.5,
                keywords=["generator", "start", "standby", "gen-001", "genset"],
            ),
            RubricItem(
                key="load_shed",
                prompt="Shed non-essential loads to fit generation.",
                guidance="Shed CIP / auxiliary loads first.",
                weight=1.5,
                keywords=["shed", "non-essential", "auxiliary", "cip", "load"],
            ),
            RubricItem(
                key="protect_critical",
                prompt="Prioritise the HP pump + essential loads.",
                guidance="Keep the HP pump and dosing on the generator.",
                weight=2.0,
                keywords=["hp pump", "high-pressure", "critical", "essential", "priorit", "dosing"],
            ),
            RubricItem(
                key="advisory_only",
                prompt="Keep the response advisory (operator approval, no control write).",
                guidance="Confirm no automatic breaker operation; approval is required.",
                weight=1.0,
                keywords=["advisory", "approval", "no control", "operator", "recommend"],
            ),
        ],
    ),
    "storm-power-loss": TrainingScenario(
        scenario_id="storm-power-loss",
        scenario_type=TrainingScenarioType.storm_power_loss,
        title="Storm & Power Loss",
        category="Power & resilience",
        difficulty="advanced",
        briefing=(
            "A storm front has knocked out the grid, feedwater turbidity is spiking "
            "and generator fuel is limited. Diagnose the compound event and decide "
            "how to protect the membranes and sustain critical loads."
        ),
        derived_from="resilience grid-outage assessment under a storm context (limited fuel)",
        learning_objectives=[
            "Handle a compound power + water-quality event.",
            "Protect the RO membranes from a turbidity excursion.",
            "Ration limited generator fuel across critical loads.",
        ],
        rubric=[
            RubricItem(
                key="power_response",
                prompt="Bring the generator on and manage limited fuel.",
                guidance="Start the generator and ration limited fuel.",
                weight=1.5,
                keywords=["generator", "fuel", "ration", "start", "power"],
            ),
            RubricItem(
                key="protect_membranes",
                prompt="Protect the membranes from the turbidity / SDI excursion.",
                guidance="Reduce flux or stand by RO to protect the membranes on high turbidity.",
                weight=2.0,
                keywords=["turbidity", "membrane", "sdi", "pretreat", "flux", "standby", "fouling"],
            ),
            RubricItem(
                key="sustain_critical",
                prompt="Sustain critical loads / service continuity.",
                guidance="Shed non-essential loads and track service continuity.",
                weight=1.5,
                keywords=["shed", "critical", "essential", "continuity", "load"],
            ),
            RubricItem(
                key="advisory_only",
                prompt="Keep the response advisory (operator approval, no control write).",
                guidance="Confirm no automatic action; approval is required.",
                weight=1.0,
                keywords=["advisory", "approval", "no control", "operator", "recommend"],
            ),
        ],
    ),
}


def list_scenarios() -> list[TrainingScenario]:
    """Return the reference training drills."""
    return list(_SCENARIOS.values())


def get_scenario(scenario_id: str) -> Optional[TrainingScenario]:
    """Return a drill by id (or ``None`` if unknown)."""
    return _SCENARIOS.get(scenario_id)


def inject_scenario(scenario_id: str, operator: str) -> TrainingSession:
    """Inject a drill: build the simulated twin snapshot and open a session.

    The injected telemetry + twin summary are derived from the platform's
    existing synthetic telemetry and read-only scenario engines; every value is
    ``provenance = "simulated"``. Nothing is written to any control system.
    """
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise KeyError(scenario_id)
    readings, summary = _INJECTORS[scenario.scenario_type]()
    return TrainingSession(
        session_id=f"train-{uuid4().hex[:12]}",
        scenario_id=scenario_id,
        scenario=scenario,
        operator=operator,
        twin_summary=summary,
        injected_telemetry=readings,
    )


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def _band_for(percentage: float) -> str:
    if percentage >= 90:
        return "Exemplary"
    if percentage >= PASS_THRESHOLD_PCT:
        return "Proficient"
    if percentage >= 45:
        return "Developing"
    return "Needs Review"


def score_actions(
    scenario: TrainingScenario, actions: list[CapturedAction]
) -> TrainingScore:
    """Score captured actions against the scenario rubric (training feedback only).

    A rubric item is credited when a captured action explicitly targets it
    (``rubric_key``) or any of its keywords appears in an action's text. Scoring
    is deterministic and side-effect free -- it never touches any control system.
    """
    haystack = " \n ".join(a.text.lower() for a in actions)
    keyed = {a.rubric_key for a in actions if a.rubric_key}

    items: list[ScoredItem] = []
    awarded_total = 0.0
    max_total = 0.0
    for item in scenario.rubric:
        max_total += item.weight
        matched = item.key in keyed or any(kw.lower() in haystack for kw in item.keywords)
        awarded = item.weight if matched else 0.0
        awarded_total += awarded
        items.append(
            ScoredItem(
                key=item.key,
                prompt=item.prompt,
                weight=item.weight,
                matched=matched,
                awarded=awarded,
                feedback=("Addressed." if matched else f"Missed: {item.guidance}"),
            )
        )

    percentage = round((awarded_total / max_total) * 100, 1) if max_total > 0 else 0.0
    return TrainingScore(
        total_score=round(awarded_total, 3),
        max_score=round(max_total, 3),
        percentage=percentage,
        band=_band_for(percentage),
        passed=percentage >= PASS_THRESHOLD_PCT,
        items=items,
    )


def build_training_record(
    session: TrainingSession, score: TrainingScore
) -> TrainingRecord:
    """Produce a durable training record for a scored drill (simulation only)."""
    return TrainingRecord(
        record_id=f"trec-{uuid4().hex[:12]}",
        session_id=session.session_id,
        scenario_id=session.scenario_id,
        scenario_title=session.scenario.title,
        operator=session.operator,
        score=score,
        actions=session.actions,
        started_at=session.started_at,
    )


# --------------------------------------------------------------------------- #
# In-memory session + record store (advisory simulation data only)
# --------------------------------------------------------------------------- #


class TrainingStore:
    """Thread-safe in-memory store of training sessions + records.

    Holds simulation-only artifacts (drills, captured actions, scores). It never
    persists to, or reads from, any control system.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, TrainingSession] = {}
        self._sandboxes: dict[str, TrainingSandbox] = {}
        self._records: dict[str, TrainingRecord] = {}

    def open_session(self, session: TrainingSession) -> TrainingSession:
        with self._lock:
            self._sessions[session.session_id] = session
            self._sandboxes[session.session_id] = TrainingSandbox()
            return session

    def get_session(self, session_id: str) -> Optional[TrainingSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def capture_action(
        self,
        session_id: str,
        kind: str,
        text: str,
        rubric_key: Optional[str] = None,
        approved: Optional[bool] = None,
    ) -> Optional[CapturedAction]:
        """Record an operator action in the session's sandbox (no control write)."""
        with self._lock:
            session = self._sessions.get(session_id)
            sandbox = self._sandboxes.get(session_id)
            if session is None or sandbox is None:
                return None
            action = sandbox.record_action(kind, text, rubric_key=rubric_key, approved=approved)
            session.actions = sandbox.actions
            return action

    def score_session(self, session_id: str) -> Optional[TrainingRecord]:
        """Score a session against its rubric and store the training record."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            score = score_actions(session.scenario, session.actions)
            record = build_training_record(session, score)
            session.status = "scored"
            self._records[record.record_id] = record
            return record

    def list_records(self) -> list[TrainingRecord]:
        with self._lock:
            return list(self._records.values())

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._sandboxes.clear()
            self._records.clear()
