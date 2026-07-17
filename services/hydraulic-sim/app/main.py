"""FastAPI app for the hydraulic-simulation service (read-only what-if).

Exposes async scenario endpoints that persist job state through the shared job
store and run the EPANET/WNTR engine in the background. Every result carries
``provenance="simulated"`` and ``status="preliminary"`` and the service never
writes to any control system (see /health control-boundary fields).
"""

from __future__ import annotations

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from canonical_water_model import ControlBoundary
from simulation_contracts import (
    JobState,
    ScenarioType,
    SimulationJob,
    SimulationRequest,
    now_iso,
)

from . import config
from .engine import ScenarioError, run_simulation
from .jobstore import JobStore
from .network import (
    DEMAND_NODES,
    PUMPS,
    SUPPLY_NODES,
    TANKS,
    VALVES,
    load_network,
)

app = FastAPI(
    title="S3M-WaterTwin Hydraulic Simulation",
    version=config.SERVICE_VERSION,
    description="Read-only EPANET/WNTR what-if hydraulic simulation for RO-TRAIN-001.",
)

store = JobStore(config.JOB_STORE_PATH)

# Observability: JSON logging, correlation ids, Prometheus metrics (+ /metrics)
# and OpenTelemetry traces; publishes the queued/running job buffer depth.
from . import observability  # noqa: E402

observability.setup(app, store=store)


def _control_boundary() -> ControlBoundary:
    return ControlBoundary(
        control_mode=config.CONTROL_MODE,
        operator_approval_required=True,
        control_write_enabled=False,
    )


def _run_job(job_id: str) -> None:
    """Background worker: execute a queued job and persist its result."""
    job = store.get(job_id)
    if job is None:
        return
    job.state = JobState.running
    store.put(job)
    try:
        result = run_simulation(job.request, inp_path=config.NETWORK_INP_PATH)
        result.job_id = job_id
        result.completed_at = now_iso()
        result.control_boundary = _control_boundary()
        job.result = result
        job.state = JobState.completed
    except ScenarioError as exc:
        job.state = JobState.failed
        job.error = f"scenario error: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        job.state = JobState.failed
        job.error = f"engine error: {exc}"
    store.put(job)


def _submit(request: SimulationRequest, background: BackgroundTasks) -> JSONResponse:
    job = SimulationJob(scenario=request.scenario, request=request)
    store.put(job)
    background.add_task(_run_job, job.job_id)
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job.job_id,
            "state": job.state.value,
            "scenario": job.scenario.value,
            "status_url": f"/api/v1/hydraulics/jobs/{job.job_id}",
        },
    )


@app.post("/api/v1/hydraulics/simulate", status_code=202)
def simulate(request: SimulationRequest, background: BackgroundTasks) -> JSONResponse:
    """Run a scenario (defaults to the baseline snapshot)."""
    return _submit(request, background)


@app.post("/api/v1/hydraulics/pump-outage", status_code=202)
def pump_outage(request: SimulationRequest, background: BackgroundTasks) -> JSONResponse:
    request.scenario = ScenarioType.pump_outage
    return _submit(request, background)


@app.post("/api/v1/hydraulics/valve-closure", status_code=202)
def valve_closure(request: SimulationRequest, background: BackgroundTasks) -> JSONResponse:
    request.scenario = ScenarioType.valve_closure
    return _submit(request, background)


@app.post("/api/v1/hydraulics/demand-change", status_code=202)
def demand_change(request: SimulationRequest, background: BackgroundTasks) -> JSONResponse:
    request.scenario = ScenarioType.demand_change
    return _submit(request, background)


@app.post("/api/v1/hydraulics/leak", status_code=202)
def leak(request: SimulationRequest, background: BackgroundTasks) -> JSONResponse:
    request.scenario = ScenarioType.leak
    return _submit(request, background)


@app.get("/api/v1/hydraulics/jobs/{job_id}")
def get_job(job_id: str) -> SimulationJob:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job '{job_id}'.")
    return job


@app.get("/api/v1/hydraulics/network")
def network_info() -> dict:
    """Describe the simulated network so clients can build scenario forms."""
    return {
        "network_id": "ro-handoff",
        "train_id": "RO-TRAIN-001",
        "pumps": PUMPS,
        "valves": VALVES,
        "tanks": TANKS,
        "demand_nodes": DEMAND_NODES,
        "supply_nodes": SUPPLY_NODES,
        "engine": "EPANET (via WNTR)",
    }


@app.get("/health")
def health() -> dict:
    """Liveness + control-boundary fields required at the control boundary."""
    cb = _control_boundary()
    network_ready = True
    detail = "ok"
    try:
        load_network(config.NETWORK_INP_PATH)
    except Exception as exc:  # pragma: no cover - defensive
        network_ready = False
        detail = f"network load failed: {exc}"
    return {
        "service": config.SERVICE_NAME,
        "version": config.SERVICE_VERSION,
        "status": "healthy" if network_ready else "degraded",
        "network_ready": network_ready,
        "detail": detail,
        "engine": "EPANET (via WNTR)",
        "provenance": "simulated",
        "control_mode": cb.control_mode,
        "operator_approval_required": cb.operator_approval_required,
        "control_write_enabled": cb.control_write_enabled,
        "control_boundary": cb.model_dump(),
    }
