"""S3M-WaterTwin reference API (Phase 7 dashboard stand-in).

Exposes the ``/api/v1`` surface the operator dashboard consumes and, in
production, serves the built dashboard from a static mount so ``docker compose
up`` is a single command. Every payload carries provenance so the UI can render
honest synthetic/preliminary badges. This is an advisory, no-write system: the
control boundary is fixed to advisory mode.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .canonical_water_model import ApprovalStatus
from .overview import build_overview
from .synthetic import (
    ASSET_INDEX,
    ASSETS,
    STREAMS,
    anomaly_for,
    health_for,
    pump_curve,
    telemetry_for,
)
from . import store

app = FastAPI(
    title="S3M-WaterTwin Reference API",
    version="0.7.0",
    description="Advisory, no-write reference API for the operator dashboard (Phase 7).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api/v1"


@app.get(f"{API}/health")
def api_liveness() -> dict:
    return {"status": "ok", "control_mode": store.CONTROL_BOUNDARY.control_mode}


@app.get(f"{API}/control-boundary")
def get_control_boundary():
    return store.CONTROL_BOUNDARY


@app.get(f"{API}/overview")
def get_overview():
    return build_overview()


@app.get(f"{API}/assets")
def get_assets():
    return ASSETS


@app.get(f"{API}/assets/{{asset_id}}")
def get_asset(asset_id: str):
    asset = ASSET_INDEX.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return asset


@app.get(f"{API}/streams")
def get_streams():
    return STREAMS


@app.get(f"{API}/health-scores")
def get_health_scores():
    return [health_for(a.asset_id) for a in ASSETS]


@app.get(f"{API}/health-scores/{{asset_id}}")
def get_health_score(asset_id: str):
    if asset_id not in ASSET_INDEX:
        raise HTTPException(status_code=404, detail="asset not found")
    return health_for(asset_id)


@app.get(f"{API}/anomaly")
def get_anomalies():
    return [anomaly_for(a.asset_id) for a in ASSETS]


@app.get(f"{API}/anomaly/{{asset_id}}")
def get_anomaly(asset_id: str):
    if asset_id not in ASSET_INDEX:
        raise HTTPException(status_code=404, detail="asset not found")
    return anomaly_for(asset_id)


@app.get(f"{API}/telemetry/{{asset_id}}")
def get_telemetry(asset_id: str):
    if asset_id not in ASSET_INDEX:
        raise HTTPException(status_code=404, detail="asset not found")
    return telemetry_for(asset_id)


@app.get(f"{API}/pump-curve/{{asset_id}}")
def get_pump_curve(asset_id: str):
    if asset_id not in ASSET_INDEX:
        raise HTTPException(status_code=404, detail="asset not found")
    return pump_curve(asset_id)


@app.get(f"{API}/recommendations")
def get_recommendations(asset_id: Optional[str] = None):
    return store.list_recommendations(asset_id)


class AskRequest(BaseModel):
    asset_id: str


@app.post(f"{API}/recommendations", status_code=201)
def ask_s3m(req: AskRequest):
    if req.asset_id not in ASSET_INDEX:
        raise HTTPException(status_code=404, detail="asset not found")
    return store.generate_recommendation(req.asset_id)


class DecisionRequest(BaseModel):
    operator: str = "operator"
    note: Optional[str] = None


@app.post(f"{API}/recommendations/{{rec_id}}/approve")
def approve_recommendation(rec_id: str, req: DecisionRequest):
    card = store.decide_recommendation(rec_id, ApprovalStatus.approved, req.operator, req.note)
    if card is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    return card


@app.post(f"{API}/recommendations/{{rec_id}}/reject")
def reject_recommendation(rec_id: str, req: DecisionRequest):
    card = store.decide_recommendation(rec_id, ApprovalStatus.rejected, req.operator, req.note)
    if card is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    return card


@app.get(f"{API}/audit")
def get_audit(asset_id: Optional[str] = None, limit: int = 100):
    return {
        "provenance": store.audit_provenance(),
        "entries": store.list_audit(asset_id, limit),
    }


# --- Static dashboard mount (production) ---------------------------------
# When the built dashboard is present (copied in the Docker image to
# ``/app/static``), serve it so the whole app runs from a single container.
_STATIC_DIR = os.environ.get("DASHBOARD_STATIC_DIR", "/app/static")

if os.path.isdir(_STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(_STATIC_DIR, "assets")), name="assets")

    @app.get("/")
    def _index():
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    @app.get("/{full_path:path}")
    def _spa(full_path: str):
        # SPA fallback: serve index.html for client-side routes, real files as-is.
        candidate = os.path.join(_STATIC_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))
