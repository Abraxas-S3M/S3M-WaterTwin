"""WaterTwin FastAPI service.

Wires together the synthetic plant, in-memory store, S3M-Core connector and the
analytics/recommendation logic behind a REST API. A background thread ticks the
plant on a fixed interval and caches the latest readings. The service is
*advisory only*: the :class:`~watertwin.boundary.ControlBoundary` is surfaced on
every health/status/recommendation response and control writes are disabled.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .analytics import compute_anomaly, compute_health
from .boundary import current_boundary
from .config import Settings
from .connector import S3MConnector
from .logging_config import configure_logging
from .models import (
    Asset,
    AuditEvent,
    DecisionRequest,
    HealthScore,
    PlantSummary,
    RecommendationCard,
    ScenarioRequest,
    TelemetryReading,
)
from .plant import SyntheticPlant
from .recommendations import generate_recommendation
from .store import Store

logger = logging.getLogger("watertwin.app")

STATIC_DIR = Path(__file__).parent / "static"
VALID_DECISIONS = {"approved", "rejected"}


class TelemetryLoop:
    """Background thread that ticks the plant and caches latest readings."""

    def __init__(self, plant: SyntheticPlant, store: Store, interval: float) -> None:
        self._plant = plant
        self._store = store
        self._interval = max(0.05, interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        # Prime the store immediately so the API has data on first request.
        self._store.ingest(self._plant.tick())
        self._thread = threading.Thread(target=self._run, name="telemetry-loop", daemon=True)
        self._thread.start()
        logger.info("telemetry loop started (interval=%.2fs)", self._interval)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._store.ingest(self._plant.tick())
            except Exception:  # pragma: no cover - defensive
                logger.exception("telemetry tick failed")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        logger.info("telemetry loop stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = getattr(app.state, "settings", None) or Settings.from_env()
    configure_logging(settings.log_level)

    plant = SyntheticPlant(seed=settings.seed)
    store = Store()
    connector = S3MConnector(base_url=settings.s3m_base_url, timeout=settings.s3m_timeout)

    app.state.settings = settings
    app.state.plant = plant
    app.state.store = store
    app.state.connector = connector

    loop = TelemetryLoop(plant, store, settings.tick_seconds)
    loop.start()
    app.state.loop = loop
    logger.info("WaterTwin API %s ready", __version__)
    try:
        yield
    finally:
        loop.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="S3M-WaterTwin API",
        version=__version__,
        description=(
            "Advisory digital twin for a water-treatment plant. Read-only with "
            "respect to plant control; every response carries the control boundary."
        ),
        lifespan=lifespan,
    )

    def get_plant() -> SyntheticPlant:
        return app.state.plant

    def get_store() -> Store:
        return app.state.store

    def get_connector() -> S3MConnector:
        return app.state.connector

    def require_asset(asset_id: str) -> Asset:
        asset = get_plant().get_asset(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail=f"unknown asset: {asset_id}")
        return asset

    @app.get("/health")
    def health() -> dict[str, Any]:
        boundary = current_boundary()
        return {
            "status": "ok",
            "version": __version__,
            "db_connected": get_store().db_connected,
            "control_mode": boundary.control_mode,
            "control_write_enabled": boundary.control_write_enabled,
        }

    @app.get("/api/v1/status", response_model=PlantSummary)
    def status() -> PlantSummary:
        plant = get_plant()
        assets = plant.assets()
        running = sum(1 for a in assets if a.status == "running")
        faulted = sum(1 for a in assets if a.status == "fault")
        return PlantSummary(
            scenario=plant.scenario,
            tick_count=plant.tick_count,
            asset_count=len(assets),
            running=running,
            faulted=faulted,
            last_tick=plant.last_tick,
            control_boundary=current_boundary(),
        )

    @app.get("/api/v1/assets")
    def list_assets() -> dict[str, list[Asset]]:
        return {"assets": get_plant().assets()}

    @app.get("/api/v1/assets/{asset_id}", response_model=Asset)
    def get_asset(asset_id: str) -> Asset:
        return require_asset(asset_id)

    @app.get("/api/v1/telemetry/latest")
    def telemetry_latest() -> dict[str, list[TelemetryReading]]:
        return {"readings": get_store().latest_all()}

    @app.get("/api/v1/analytics/health/{asset_id}", response_model=HealthScore)
    def analytics_health(asset_id: str) -> HealthScore:
        require_asset(asset_id)
        store = get_store()
        plant = get_plant()
        return compute_health(asset_id, store.latest_for(asset_id), plant.metric_specs(asset_id))

    @app.get("/api/v1/analytics/anomaly/{asset_id}")
    def analytics_anomaly(asset_id: str):
        require_asset(asset_id)
        store = get_store()
        plant = get_plant()
        return compute_anomaly(asset_id, store.history_for(asset_id), plant.metric_specs(asset_id))

    @app.post("/api/v1/recommendations/generate/{asset_id}", response_model=RecommendationCard)
    def recommendations_generate(asset_id: str) -> RecommendationCard:
        require_asset(asset_id)
        return generate_recommendation(
            asset_id, get_plant(), get_store(), get_connector(), actor="system"
        )

    @app.get("/api/v1/recommendations")
    def list_recommendations() -> dict[str, list[RecommendationCard]]:
        return {"recommendations": get_store().recommendations()}

    @app.post("/api/v1/recommendations/{rec_id}/decision", response_model=RecommendationCard)
    def recommendation_decision(rec_id: str, body: DecisionRequest) -> RecommendationCard:
        status_value = body.status.lower().strip()
        if status_value not in VALID_DECISIONS:
            raise HTTPException(
                status_code=422,
                detail=f"status must be one of {sorted(VALID_DECISIONS)}",
            )
        store = get_store()
        if store.get_recommendation(rec_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown recommendation: {rec_id}")
        updated = store.set_approval(rec_id, status_value, body.actor)
        assert updated is not None
        store.add_audit(
            event_type="recommendation.decision",
            actor=body.actor,
            subject=rec_id,
            details={"status": status_value, "asset_id": updated.asset_id},
        )
        return updated

    @app.post("/api/v1/scenario")
    def set_scenario(body: ScenarioRequest) -> dict[str, Any]:
        plant = get_plant()
        try:
            plant.set_scenario(body.scenario)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        get_store().add_audit(
            event_type="scenario.set", actor="system", subject=body.scenario, details={}
        )
        return {"scenario": plant.scenario, "control_boundary": current_boundary().model_dump()}

    @app.post("/api/v1/reset")
    def reset() -> dict[str, Any]:
        plant = get_plant()
        store = get_store()
        plant.reset()
        store.reset()
        store.ingest(plant.tick())
        store.add_audit(event_type="plant.reset", actor="system", subject="plant", details={})
        return {
            "status": "reset",
            "scenario": plant.scenario,
            "tick_count": plant.tick_count,
            "control_boundary": current_boundary().model_dump(),
        }

    @app.get("/api/v1/audit")
    def audit(limit: int = 100) -> dict[str, list[AuditEvent]]:
        return {"events": get_store().audit_events(limit=limit)}

    @app.get("/", include_in_schema=False)
    def dashboard_root():
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"message": "WaterTwin API", "version": __version__})

    if STATIC_DIR.exists():
        app.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="app")

    return app


app = create_app()
