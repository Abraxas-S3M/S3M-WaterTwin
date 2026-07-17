"""FastAPI application for the read-only RO process-simulation service.

Endpoints (async jobs):

* ``POST /api/v1/process/simulate``            - baseline RO
* ``POST /api/v1/process/optimize``            - minimize specific energy
* ``POST /api/v1/process/sensitivity``         - sweep salinity/temperature/pressure
* ``POST /api/v1/process/membrane-degradation``- A/B permeability decline impact
* ``GET  /api/v1/process/jobs/{job_id}``       - poll a job
* ``GET  /health``                             - health + control-boundary fields

Every result carries ``provenance="simulated"`` and ``status="preliminary"``.
This service performs read-only what-if / optimization only; it never writes to
any control system.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from simulation_contracts import (
    HealthResponse,
    MembraneDegradationRequest,
    OptimizeRequest,
    SensitivityRequest,
    SimulateRequest,
    SimulationJob,
    SimulationKind,
)

from . import engine, watertap_engine
from .jobs import store

app = FastAPI(
    title="S3M-WaterTwin treatment-sim",
    version="0.1.0",
    description=(
        "Read-only reverse-osmosis process simulation (WaterTAP/IDAES). "
        "What-if and optimization only; advisory, never closed-loop control."
    ),
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        engine=engine.active_engine(),
        watertap_available=watertap_engine.watertap_available(),
        solver_available=watertap_engine.solver_available(),
    )


@app.post("/api/v1/process/simulate", response_model=SimulationJob, status_code=202)
async def simulate(req: SimulateRequest) -> SimulationJob:
    job = await store.create(
        SimulationKind.simulate, req.model_dump(mode="json"), req.scenario_id
    )
    store.submit(job, lambda: engine.run_simulate(req))
    return job


@app.post("/api/v1/process/optimize", response_model=SimulationJob, status_code=202)
async def optimize(req: OptimizeRequest) -> SimulationJob:
    job = await store.create(
        SimulationKind.optimize, req.model_dump(mode="json"), req.scenario_id
    )
    store.submit(job, lambda: engine.run_optimize(req))
    return job


@app.post("/api/v1/process/sensitivity", response_model=SimulationJob, status_code=202)
async def sensitivity(req: SensitivityRequest) -> SimulationJob:
    job = await store.create(
        SimulationKind.sensitivity, req.model_dump(mode="json"), req.scenario_id
    )
    store.submit(job, lambda: engine.run_sensitivity(req))
    return job


@app.post(
    "/api/v1/process/membrane-degradation",
    response_model=SimulationJob,
    status_code=202,
)
async def membrane_degradation(req: MembraneDegradationRequest) -> SimulationJob:
    job = await store.create(
        SimulationKind.membrane_degradation,
        req.model_dump(mode="json"),
        req.scenario_id,
    )
    store.submit(job, lambda: engine.run_membrane_degradation(req))
    return job


@app.get("/api/v1/process/jobs/{job_id}", response_model=SimulationJob)
async def get_job(job_id: str) -> SimulationJob:
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job
