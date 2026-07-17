"""watertwin-api: Simulation Center orchestration + recommendations.

Drives the hydraulic-sim service (read-only what-if), returns baseline-vs-scenario
comparisons for the dashboard Simulation Center, and produces recommendation cards
with the run's ``simulation_id`` attached to ``evidence.simulation_ids``.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from canonical_water_model import ControlBoundary
from simulation_contracts import ScenarioType, SimulationResult

from . import config
from .hydraulic_client import HydraulicSimClient, HydraulicSimError
from .recommendations import RecommendationStore, build_recommendation

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

    return {
        "scenario": request.scenario.value,
        "baseline": baseline.model_dump(mode="json"),
        "scenario_result": scenario.model_dump(mode="json"),
        "comparison": _comparison(baseline, scenario),
        "confidence": scenario.confidence,
        "simulation_ids": [baseline.simulation_id, scenario.simulation_id],
        "recommendation": recommendation,
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get("/api/v1/recommendations")
def list_recommendations() -> list[dict]:
    return [c.model_dump(mode="json") for c in reco_store.list()]


@app.get("/api/v1/recommendations/{recommendation_id}")
def get_recommendation(recommendation_id: str) -> dict:
    card = reco_store.get(recommendation_id)
    if card is None:
        raise HTTPException(status_code=404, detail="unknown recommendation")
    return card.model_dump(mode="json")
