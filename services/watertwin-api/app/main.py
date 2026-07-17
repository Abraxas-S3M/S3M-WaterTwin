"""watertwin-api: Simulation Center orchestration + recommendations.

Drives the hydraulic-sim service (read-only what-if), returns baseline-vs-scenario
comparisons for the dashboard Simulation Center, and produces recommendation cards
with the run's ``simulation_id`` attached to ``evidence.simulation_ids``.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from canonical_water_model import ControlBoundary
from simulation_contracts import ScenarioType, SimulationResult

from . import config
from .hydraulic_client import HydraulicSimClient, HydraulicSimError
from .recommendations import RecommendationStore, build_recommendation
from .reports import build_scenario_report
from .store import Store

app = FastAPI(
    title="S3M-WaterTwin API",
    version=config.SERVICE_VERSION,
    description="Orchestration API for the S3M-WaterTwin Simulation Center.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

reco_store = RecommendationStore(config.RECOMMENDATION_STORE_PATH)
store = Store(config.DATABASE_URL)

# Completed runs cached by simulation job id so a downloadable report can be
# regenerated on demand. Advisory, read-only what-if data only.
_runs: dict[str, dict[str, Any]] = {}
_runs_lock = threading.RLock()


def _cache_run(run: dict[str, Any]) -> None:
    with _runs_lock:
        for sim_id in run.get("simulation_ids", []) or []:
            if sim_id:
                _runs[sim_id] = run


def _get_run(job_id: str) -> Optional[dict[str, Any]]:
    with _runs_lock:
        return _runs.get(job_id)


def get_hydraulic_client() -> HydraulicSimClient:
    """Return the injected client (tests) or a default HTTP client."""
    client = getattr(app.state, "hydraulic_client", None)
    if client is None:
        client = HydraulicSimClient(base_url=config.HYDRAULIC_SIM_URL)
        app.state.hydraulic_client = client
    return client


class SimulationCenterRequest(BaseModel):
    scenario: ScenarioType
    parameters: dict[str, Any] = Field(default_factory=dict)
    create_recommendation: bool = True
    facility_id: str = "S3M-DESAL-01"
    train_id: str = "RO-TRAIN-001"
    requested_by: Optional[str] = None


def _comparison(baseline: SimulationResult, scenario: SimulationResult) -> dict:
    delta = scenario.outputs.delta_vs_baseline
    return {
        "delivered_flow_baseline_m3h": baseline.outputs.delivered_flow_m3h,
        "delivered_flow_scenario_m3h": scenario.outputs.delivered_flow_m3h,
        "delivered_flow_delta_m3h": (delta.delivered_flow_delta_m3h if delta else None),
        "delivered_flow_delta_pct": (delta.delivered_flow_delta_pct if delta else None),
        "min_pressure_baseline_m": (delta.min_pressure_baseline_m if delta else None),
        "min_pressure_scenario_m": (delta.min_pressure_scenario_m if delta else None),
        "pressure_delta_m": (delta.pressure_delta_m if delta else {}),
        "flow_delta_m3h": (delta.flow_delta_m3h if delta else {}),
    }


@app.get("/health")
def health() -> dict:
    cb = ControlBoundary()
    sim_health: dict[str, Any]
    try:
        sim_health = get_hydraulic_client().health()
        sim_ok = sim_health.get("status") == "healthy"
    except Exception as exc:  # pragma: no cover - depends on env
        sim_health = {"error": str(exc)}
        sim_ok = False
    return {
        "service": config.SERVICE_NAME,
        "version": config.SERVICE_VERSION,
        "status": "healthy",
        "hydraulic_sim_reachable": sim_ok,
        "hydraulic_sim": sim_health,
        "db_connected": store.db_connected,
        "control_mode": cb.control_mode,
        "operator_approval_required": cb.operator_approval_required,
        "control_write_enabled": cb.control_write_enabled,
        "control_boundary": cb.model_dump(),
    }


@app.get("/api/v1/simulation-center/network")
def network() -> dict:
    try:
        return get_hydraulic_client().network_info()
    except HydraulicSimError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/v1/simulation-center/run")
def run_scenario(request: SimulationCenterRequest) -> dict:
    """Run baseline + scenario and (optionally) create a recommendation."""
    client = get_hydraulic_client()
    try:
        baseline = client.run(
            ScenarioType.baseline,
            facility_id=request.facility_id,
            train_id=request.train_id,
        )
        scenario = client.run(
            request.scenario,
            parameters=request.parameters,
            facility_id=request.facility_id,
            train_id=request.train_id,
            requested_by=request.requested_by,
        )
    except HydraulicSimError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    recommendation = None
    if request.create_recommendation and request.scenario != ScenarioType.baseline:
        card = build_recommendation(
            scenario, facility_id=request.facility_id, train_id=request.train_id
        )
        reco_store.put(card)
        recommendation = card.model_dump(mode="json")
        store.save_recommendation(
            card.recommendation_id,
            recommendation,
            facility_id=request.facility_id,
            train_id=request.train_id,
            status=card.approval_status.value,
        )
        store.audit(
            "recommendation.created",
            payload={
                "recommendation_id": card.recommendation_id,
                "scenario": request.scenario.value,
                "simulation_ids": card.evidence.simulation_ids,
            },
            subject=card.recommendation_id,
        )

    run = {
        "scenario": request.scenario.value,
        "facility_id": request.facility_id,
        "train_id": request.train_id,
        "baseline": baseline.model_dump(mode="json"),
        "scenario_result": scenario.model_dump(mode="json"),
        "comparison": _comparison(baseline, scenario),
        "confidence": scenario.confidence,
        "simulation_ids": [baseline.simulation_id, scenario.simulation_id],
        "recommendation": recommendation,
        "control_boundary": ControlBoundary().model_dump(),
    }
    _cache_run(run)
    store.audit(
        "scenario.run",
        payload={
            "scenario": request.scenario.value,
            "simulation_ids": run["simulation_ids"],
        },
        subject=scenario.simulation_id,
    )
    return run


@app.get("/api/v1/recommendations")
def list_recommendations() -> list[dict]:
    return [c.model_dump(mode="json") for c in reco_store.list()]


@app.get("/api/v1/recommendations/{recommendation_id}")
def get_recommendation(recommendation_id: str) -> dict:
    card = reco_store.get(recommendation_id)
    if card is None:
        raise HTTPException(status_code=404, detail="unknown recommendation")
    return card.model_dump(mode="json")


class DecisionRequest(BaseModel):
    status: str = Field(description="approved or rejected")
    actor: str = "operator"


_VALID_DECISIONS = {"approved", "rejected"}


@app.post("/api/v1/recommendations/{recommendation_id}/decision")
def decide_recommendation(recommendation_id: str, body: DecisionRequest) -> dict:
    """Record an operator approval decision.

    This is an *operator approval* action only; it never writes to equipment.
    """
    decision = body.status.lower().strip()
    if decision not in _VALID_DECISIONS:
        raise HTTPException(
            status_code=422, detail=f"status must be one of {sorted(_VALID_DECISIONS)}"
        )
    card = reco_store.get(recommendation_id)
    if card is None:
        raise HTTPException(status_code=404, detail="unknown recommendation")
    from canonical_water_model import ApprovalStatus

    card.approval_status = ApprovalStatus(decision)
    reco_store.put(card)
    store.set_status(recommendation_id, decision)
    store.audit(
        "recommendation.decision",
        payload={"recommendation_id": recommendation_id, "status": decision},
        actor=body.actor,
        subject=recommendation_id,
    )
    return card.model_dump(mode="json")


@app.get("/api/v1/audit")
def audit_log(limit: int = 100) -> dict:
    return {"events": store.recent_audit(limit)}


@app.post("/api/v1/reset")
def reset() -> dict:
    """Clear cached runs, recommendations, and audit trail (demo convenience)."""
    with _runs_lock:
        _runs.clear()
    reco_store.clear()
    store.reset()
    store.audit("system.reset", subject="watertwin-api")
    return {"status": "reset", "control_boundary": ControlBoundary().model_dump()}


@app.post("/api/v1/reports/scenario/{job_id}")
def scenario_report(job_id: str) -> PlainTextResponse:
    """Generate a downloadable Markdown scenario report for a completed run.

    The document carries baseline-vs-scenario impacts, the recommended response,
    confidence, full provenance, and a mandatory read-only control-boundary
    footer.
    """
    run = _get_run(job_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown simulation job: {job_id}")
    document = build_scenario_report(job_id, run)
    store.audit(
        "report.generated",
        payload={"job_id": job_id, "scenario": run.get("scenario")},
        subject=job_id,
    )
    filename = f"scenario-report-{job_id}.md"
    return PlainTextResponse(
        content=document,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
