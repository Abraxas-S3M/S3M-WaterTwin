"""watertwin-api: Simulation Center orchestration + recommendations.

Drives the hydraulic-sim service (read-only what-if), returns baseline-vs-scenario
comparisons for the dashboard Simulation Center, and produces recommendation cards
with the run's ``simulation_id`` attached to ``evidence.simulation_ids``.
"""

from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from canonical_water_model import ControlBoundary, DataProvenance, WQAlert

from simulation_contracts import ScenarioType, SimulationResult

from . import auth
from . import config
from .auth import (
    Principal,
    get_current_user,
    require_role,
)
from . import assistant
from . import documents
from . import energy
from . import executive
from . import licensing
from . import log_buffer
from . import membrane
from .metering import meter
from . import predictive_maintenance as pdm
from . import resilience as resil
from . import sources
from . import support
from . import updates
from . import water_quality as wq
from .tag_normalization import RawReading, TagMap, TagMapError, load_tag_map, normalize
from .hydraulic_client import HydraulicSimClient, HydraulicSimError
from .recommendations import RecommendationStore, build_recommendation
from .reports import build_scenario_report
from .store import Store

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Log whether auth is enforced or bypassed (explicit dev mode) at startup.
    auth.log_auth_mode()
    yield


app = FastAPI(
    title="S3M-WaterTwin API",
    version=config.SERVICE_VERSION,
    description="Orchestration API for the S3M-WaterTwin Simulation Center.",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Log whether auth is enforced or bypassed (explicit dev mode) at import too, so
# the mode is visible even when the app is mounted without the lifespan hook.
auth.log_auth_mode()

# Retain a tail of recent logs in memory so an administrator can package them
# into a redacted support bundle (see app/support.py). Advisory logs only.
log_buffer.install()


# Reusable dependency: any authenticated role may read advisory views. Under the
# ``WATERTWIN_AUTH_DISABLED=true`` dev bypass this resolves to a synthetic admin.
AUTHENTICATED = [Depends(get_current_user)]

# Feature-gated dependency lists: authenticated *and* the tenant's plan must
# include the feature (otherwise 402 Payment Required). Feature-gating hides
# advisory features by plan; it NEVER touches the advisory/read-only safety
# invariant (see app/licensing.py). The default plan (``enterprise``) includes
# every feature, so a default deployment gates nothing.
FEAT_WATER_QUALITY = licensing.authed_feature(licensing.FEATURE_WATER_QUALITY)
FEAT_PREDICTIVE_MAINTENANCE = licensing.authed_feature(
    licensing.FEATURE_PREDICTIVE_MAINTENANCE
)
FEAT_ENERGY = licensing.authed_feature(licensing.FEATURE_ENERGY_OPTIMIZATION)
FEAT_RESILIENCE = licensing.authed_feature(licensing.FEATURE_RESILIENCE)
FEAT_EXECUTIVE = licensing.authed_feature(licensing.FEATURE_EXECUTIVE_VALUE)
FEAT_ASSISTANT = licensing.authed_feature(licensing.FEATURE_OPERATIONS_ASSISTANT)


def _actor(user: Principal, fallback: str | None = None) -> str:
    """Audit actor for an action.

    When auth is enforced the authenticated identity is authoritative (a
    client-supplied actor is never trusted). Under the dev bypass we preserve
    the legacy behaviour of honouring an explicit fallback actor when provided.
    """
    if auth.auth_disabled() and fallback:
        return fallback
    return user.actor


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


# Active telemetry source, resolved lazily from OT_SOURCE with graceful fallback
# to synthetic. Cached process-wide; tests may inject via ``app.state``.
_source_resolution: Optional[sources.SourceResolution] = None


def get_source_resolution() -> sources.SourceResolution:
    """Return the active telemetry-source resolution (injected in tests, else cached)."""
    override = getattr(app.state, "source_resolution", None)
    if override is not None:
        return override
    global _source_resolution
    if _source_resolution is None:
        _source_resolution = sources.resolve_source(config)
    return _source_resolution


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
    try:
        resolution = get_source_resolution()
        telemetry = resolution.describe()
    except Exception as exc:  # pragma: no cover - defensive; resolver never raises
        telemetry = {"error": str(exc)}
    return {
        "service": config.SERVICE_NAME,
        "version": config.SERVICE_VERSION,
        "status": "healthy",
        "hydraulic_sim_reachable": sim_ok,
        "hydraulic_sim": sim_health,
        "db_connected": store.db_connected,
        "telemetry_source": telemetry.get("active_source"),
        "telemetry_source_requested": telemetry.get("requested_source"),
        "telemetry_source_fallback": telemetry.get("fallback"),
        "telemetry": telemetry,
        "control_mode": cb.control_mode,
        "operator_approval_required": cb.operator_approval_required,
        "control_write_enabled": cb.control_write_enabled,
        "control_boundary": cb.model_dump(),
    }


@app.get("/api/v1/simulation-center/network", dependencies=AUTHENTICATED)
def network() -> dict:
    try:
        return get_hydraulic_client().network_info()
    except HydraulicSimError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/v1/simulation-center/run")
def run_scenario(
    request: SimulationCenterRequest,
    user: Principal = Depends(require_role("engineer")),
) -> dict:
    """Run baseline + scenario and (optionally) create a recommendation.

    Running a what-if scenario is an engineer/admin action (RBAC matrix).
    """
    # Usage metering (billing export): count the facility and the run.
    meter.record_facility(request.facility_id)
    meter.record_api_call("scenario_run")
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
            actor=_actor(user),
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
        actor=_actor(user),
        subject=scenario.simulation_id,
    )
    return run


@app.get("/api/v1/recommendations", dependencies=AUTHENTICATED)
def list_recommendations() -> list[dict]:
    return [c.model_dump(mode="json") for c in reco_store.list()]


@app.get("/api/v1/recommendations/{recommendation_id}", dependencies=AUTHENTICATED)
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
def decide_recommendation(
    recommendation_id: str,
    body: DecisionRequest,
    user: Principal = Depends(require_role("operator")),
) -> dict:
    """Record an operator approval decision.

    This is an *operator approval* action only; it never writes to equipment.
    Approving/rejecting a recommendation is an operator/admin action (RBAC
    matrix) and the authenticated identity is recorded as the audit actor.
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

    actor = _actor(user, body.actor)
    card.approval_status = ApprovalStatus(decision)
    reco_store.put(card)
    store.set_status(recommendation_id, decision)
    store.audit(
        "recommendation.decision",
        payload={"recommendation_id": recommendation_id, "status": decision},
        actor=actor,
        subject=recommendation_id,
    )
    return card.model_dump(mode="json")


@app.get("/api/v1/audit", dependencies=[Depends(require_role("auditor"))])
def audit_log(limit: int = 100) -> dict:
    """Read the audit trail (auditor/admin role required)."""
    return {"events": store.recent_audit(limit)}


@app.get("/api/v1/audit/verify", dependencies=[Depends(require_role("auditor"))])
def audit_verify() -> dict:
    """Verify the tamper-evident audit hash chain (auditor/admin role required).

    Re-walks the append-only chain and returns ``{"ok": true, ...}`` when every
    event's link and content hash are intact, or ``{"ok": false, "broken_at":
    <event id>, ...}`` identifying the first event that fails validation (e.g. a
    payload that was altered after the fact).
    """
    return store.verify_chain()


# ---------------------------------------------------------------------------
# Ingestion: telemetry source status + tag-normalization preview (read-only)
#
# Telemetry is a pluggable, strictly read-only source (synthetic default; real
# OT feed via OPC UA / Modbus / historian). ``GET .../ingestion/source`` reports
# the active source + fallback state. ``POST .../ingestion/normalize/preview``
# dry-runs a customer tag map against sample raw values (mapping onto the
# canonical model, with unmapped/invalid tags rejected) -- a pure read transform
# that persists nothing and touches no control system.
# ---------------------------------------------------------------------------


class RawReadingInput(BaseModel):
    customer_tag: str
    value: Any = None
    timestamp: Optional[str] = None
    quality: Optional[str] = None


class NormalizePreviewRequest(BaseModel):
    readings: list[RawReadingInput] = Field(default_factory=list)
    #: A tag-map name (under data/tag-maps/) or a path. Ignored if inline given.
    tag_map: Optional[str] = None
    #: An inline tag map ({"tags": {...}}) to dry-run without a config file.
    tag_map_inline: Optional[dict] = None


@app.get("/api/v1/ingestion/source", dependencies=AUTHENTICATED)
def ingestion_source() -> dict:
    """Report the active telemetry source and any fallback to synthetic."""
    resolution = get_source_resolution()
    return {
        **resolution.describe(),
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.post("/api/v1/ingestion/normalize/preview", dependencies=AUTHENTICATED)
def ingestion_normalize_preview(body: NormalizePreviewRequest) -> dict:
    """Dry-run a tag map against sample raw values (read-only, no persistence)."""
    try:
        if body.tag_map_inline is not None:
            tag_map = TagMap.from_dict(body.tag_map_inline)
        elif body.tag_map:
            tag_map = load_tag_map(body.tag_map)
        else:
            raise HTTPException(
                status_code=422,
                detail="provide either 'tag_map' (name/path) or 'tag_map_inline'",
            )
    except TagMapError as exc:
        raise HTTPException(status_code=422, detail=f"invalid tag map: {exc}")

    raw = [
        RawReading(
            customer_tag=r.customer_tag,
            value=r.value,
            timestamp=r.timestamp,
            quality=r.quality,
        )
        for r in body.readings
    ]
    # Usage metering (billing export): count ingest volume (readings brought in
    # through the read-only ingestion path).
    meter.record_ingest(len(raw))
    result = normalize(raw, tag_map)
    return {
        "tag_map": tag_map.map_id,
        "readings": [reading.model_dump(mode="json") for reading in result.readings],
        "rejected": [
            {"customer_tag": rej.customer_tag, "value": rej.value, "reason": rej.reason}
            for rej in result.rejected
        ],
        "summary": {
            "total": len(raw),
            "mapped": len(result.readings),
            "rejected": len(result.rejected),
        },
        "control_boundary": ControlBoundary().model_dump(),
    }


# ---------------------------------------------------------------------------
# Water Quality Intelligence (advisory, read-only)
#
# Deterministic water-quality calculations, scaling/fouling/boron forecasts and
# alerts. Every response carries the control boundary + provenance; forecasts
# and risks are preliminary engineering estimates (never validated production
# predictions or guaranteed compliance). Alerts route through the existing
# recommendation + audit path with operator approval required.
# ---------------------------------------------------------------------------

# Nominal fouling severity used by the synthetic generator. A caller may pass a
# ``fouling`` query parameter (0..1) to inspect a membrane-fouling scenario;
# this is read-only what-if data only.
DEFAULT_WQ_FOULING = float(os.environ.get("WATERTWIN_WQ_FOULING", "0.15"))


def _wq_fouling(fouling: Optional[float]) -> float:
    return DEFAULT_WQ_FOULING if fouling is None else max(0.0, min(1.0, fouling))


def _wq_envelope(payload: dict, provenance: DataProvenance) -> dict:
    """Attach the read-only control boundary + provenance to every WQ response."""
    return {
        **payload,
        "facility_id": wq.FACILITY_ID,
        "train_id": wq.TRAIN_ID,
        "provenance": provenance.value,
        "control_boundary": ControlBoundary().model_dump(),
    }


def _route_wq_alerts(alerts: list[WQAlert], actor: str = "system") -> None:
    """Route WQ alerts through the existing recommendation + audit path.

    Each alert becomes a ``pending`` recommendation card (operator approval
    required, no control write). Idempotent by the alert-derived id so repeated
    polling does not duplicate cards or reset an operator's decision.
    """
    for alert in alerts:
        card = wq.build_wq_recommendation(alert)
        if reco_store.get(card.recommendation_id) is not None:
            continue
        reco_store.put(card)
        store.save_recommendation(
            card.recommendation_id,
            card.model_dump(mode="json"),
            facility_id=card.facility_id,
            train_id=card.train_id,
            status=card.approval_status.value,
        )
        store.audit(
            "wq.alert.created",
            payload={"recommendation_id": card.recommendation_id, "code": alert.code},
            actor=actor,
            subject=card.recommendation_id,
        )


@app.get("/api/v1/water-quality/status", dependencies=FEAT_WATER_QUALITY)
def water_quality_status(fouling: Optional[float] = None) -> dict:
    """Live water quality by stage with compliance flags + train summary."""
    snap = wq.compute_snapshot(_wq_fouling(fouling))
    return _wq_envelope(
        {
            "stage_status": snap.stage_status,
            "samples": [s.model_dump(mode="json") for s in snap.samples],
            "summary": {
                "recovery": snap.recovery,
                "salt_rejection": snap.salt_rejection,
                "salt_passage": snap.salt_passage,
                "normalized_salt_passage": snap.normalized_salt_passage,
                "normalized_dp_bar": snap.normalized_dp_bar,
                "permeate_tds_mg_l": snap.permeate_tds_mg_l,
                "permeate_boron_mg_l": snap.permeate_boron_mg_l,
            },
        },
        DataProvenance.synthetic,
    )


@app.get("/api/v1/water-quality/contaminant-matrix", dependencies=FEAT_WATER_QUALITY)
def water_quality_contaminant_matrix(fouling: Optional[float] = None) -> dict:
    """Contaminant concentration across the treatment path (intake -> brine)."""
    snap = wq.compute_snapshot(_wq_fouling(fouling))
    return _wq_envelope(
        {"rows": [r.model_dump(mode="json") for r in snap.contaminant_matrix]},
        DataProvenance.synthetic,
    )


@app.get("/api/v1/water-quality/removal", dependencies=FEAT_WATER_QUALITY)
def water_quality_removal(fouling: Optional[float] = None) -> dict:
    """Treatment removal: current vs design vs predicted (with confidence)."""
    snap = wq.compute_snapshot(_wq_fouling(fouling))
    return _wq_envelope({"removal": snap.removal}, DataProvenance.preliminary)


@app.get("/api/v1/water-quality/scaling", dependencies=FEAT_WATER_QUALITY)
def water_quality_scaling(fouling: Optional[float] = None) -> dict:
    """Per-compound scaling risk (preliminary)."""
    snap = wq.compute_snapshot(_wq_fouling(fouling))
    return _wq_envelope(
        {"scaling": [r.model_dump(mode="json") for r in snap.scaling]},
        DataProvenance.preliminary,
    )


@app.get("/api/v1/water-quality/forecast", dependencies=FEAT_WATER_QUALITY)
def water_quality_forecast(fouling: Optional[float] = None) -> dict:
    """Preliminary forecasts: salinity, boron, scaling, fouling (bounded)."""
    snap = wq.compute_snapshot(_wq_fouling(fouling))
    return _wq_envelope(
        {"forecasts": [f.model_dump(mode="json") for f in snap.forecasts]},
        DataProvenance.preliminary,
    )


@app.get("/api/v1/water-quality/alerts", dependencies=FEAT_WATER_QUALITY)
def water_quality_alerts(
    fouling: Optional[float] = None,
    user: Principal = Depends(get_current_user),
) -> dict:
    """WQ alerts; each is routed to the recommendation + audit path (pending)."""
    snap = wq.compute_snapshot(_wq_fouling(fouling))
    _route_wq_alerts(snap.alerts, actor=_actor(user))
    return _wq_envelope(
        {
            "alerts": [a.model_dump(mode="json") for a in snap.alerts],
            "recommendations": [
                reco_store.get(f"rec-wq-{a.code.lower()}").model_dump(mode="json")
                for a in snap.alerts
                if reco_store.get(f"rec-wq-{a.code.lower()}") is not None
            ],
        },
        DataProvenance.preliminary,
    )


# ---------------------------------------------------------------------------
# Equipment & Membrane Intelligence + Predictive Maintenance (advisory, read-only)
#
# Component health, preliminary RUL + failure probability, operating envelope,
# causal root-cause ranking, membrane fouling/scaling/health (reusing the WQ
# layer) and risk-ranked predictive-maintenance recommendations. Every response
# carries the control boundary + provenance. RUL / failure-probability /
# avoided-cost are preliminary engineering estimates (never validated or
# guaranteed). PdM recommendations route through the existing recommendation +
# audit path with operator approval required and control write disabled.
# ---------------------------------------------------------------------------


def _pdm_envelope(payload: dict, provenance: DataProvenance = DataProvenance.preliminary) -> dict:
    """Attach the read-only control boundary + provenance to every PdM response."""
    return {
        **payload,
        "facility_id": wq.FACILITY_ID,
        "train_id": wq.TRAIN_ID,
        "provenance": provenance.value,
        "control_boundary": ControlBoundary().model_dump(),
    }


def _require_asset(asset_id: str) -> None:
    if asset_id not in pdm.ASSETS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown asset: {asset_id}; known: {pdm.list_asset_ids()}",
        )
    # Usage metering (billing export): count distinct assets under management.
    meter.record_asset(asset_id)


@app.get("/api/v1/equipment/{asset_id}/health", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def equipment_health(asset_id: str, fouling: Optional[float] = None) -> dict:
    """Transparent component health with a contribution breakdown."""
    _require_asset(asset_id)
    health = pdm.component_health_for(asset_id, _wq_fouling(fouling))
    return _pdm_envelope({"health": health.model_dump(mode="json")})


@app.get("/api/v1/equipment/{asset_id}/rul", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def equipment_rul(asset_id: str, fouling: Optional[float] = None) -> dict:
    """Preliminary remaining-useful-life with an uncertainty band."""
    _require_asset(asset_id)
    rul = pdm.rul_for(asset_id, _wq_fouling(fouling))
    return _pdm_envelope({"rul": rul.model_dump(mode="json")})


@app.get(
    "/api/v1/equipment/{asset_id}/failure-probability",
    dependencies=FEAT_PREDICTIVE_MAINTENANCE,
)
def equipment_failure_probability(asset_id: str, fouling: Optional[float] = None) -> dict:
    """Preliminary failure probability over {24h, 7d, 30d, 90d} horizons."""
    _require_asset(asset_id)
    fp = pdm.failure_probability_for(asset_id, _wq_fouling(fouling))
    return _pdm_envelope({"failure_probability": fp.model_dump(mode="json")})


@app.get("/api/v1/equipment/{asset_id}/envelope", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def equipment_envelope(asset_id: str) -> dict:
    """Operating-envelope regime fractions (BEP / low-flow / high-pressure / ...)."""
    _require_asset(asset_id)
    env = pdm.envelope_for(asset_id)
    return _pdm_envelope({"envelope": env.model_dump(mode="json")})


@app.get("/api/v1/equipment/{asset_id}/root-cause", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def equipment_root_cause(asset_id: str) -> dict:
    """Causal root-cause ranking (probabilities sum to ~1.0)."""
    _require_asset(asset_id)
    rc = pdm.root_cause_for(asset_id)
    return _pdm_envelope({"root_cause": rc.model_dump(mode="json")})


@app.get("/api/v1/membrane/{asset_id}/health", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def membrane_health(asset_id: str, fouling: Optional[float] = None) -> dict:
    """Membrane fouling / scaling / health (reuses the Water Quality layer)."""
    _require_asset(asset_id)
    mh = membrane.compute_membrane_health(_wq_fouling(fouling), asset_id=asset_id)
    return _pdm_envelope({"membrane": mh.model_dump(mode="json")})


def _route_pdm_recommendations(cards: list, actor: str = "system") -> None:
    """Route PdM recommendation cards through the existing recommendation + audit
    path. Each card is created ``pending`` (operator approval required, no
    control write) and is idempotent by its asset-derived id so repeated polling
    does not duplicate cards or reset an operator's decision."""
    for card in cards:
        if reco_store.get(card.recommendation_id) is not None:
            continue
        reco_store.put(card)
        store.save_recommendation(
            card.recommendation_id,
            card.model_dump(mode="json"),
            facility_id=card.facility_id,
            train_id=card.train_id,
            status=card.approval_status.value,
        )
        store.audit(
            "pdm.recommendation.created",
            payload={"recommendation_id": card.recommendation_id, "asset_id": card.asset_id},
            actor=actor,
            subject=card.recommendation_id,
        )


@app.get("/api/v1/maintenance/ranking", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def maintenance_ranking(fouling: Optional[float] = None) -> dict:
    """Risk-ranked predictive-maintenance view across all critical assets."""
    ranking = pdm.compute_ranking(_wq_fouling(fouling))
    return _pdm_envelope({"ranking": [p.model_dump(mode="json") for p in ranking]})


@app.get("/api/v1/maintenance/recommendations", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def maintenance_recommendations(
    fouling: Optional[float] = None,
    user: Principal = Depends(get_current_user),
) -> dict:
    """PdM recommendations; each routes to the recommendation + audit path (pending)."""
    recs = pdm.compute_recommendations(_wq_fouling(fouling))
    cards = [pdm.build_pdm_card(rec) for rec in recs]
    _route_pdm_recommendations(cards, actor=_actor(user))
    return _pdm_envelope(
        {
            "recommendations": [p.model_dump(mode="json") for p in recs],
            "cards": [
                reco_store.get(rec.recommendation_id).model_dump(mode="json")
                for rec in recs
                if rec.recommendation_id
                and reco_store.get(rec.recommendation_id) is not None
            ],
        }
    )


# ---------------------------------------------------------------------------
# Value layer: Energy Optimization, Resilience & Generator Command, Executive
# ROI (advisory, read-only).
#
# Energy optimisation reuses the single canonical RO model + specific-energy;
# resilience assesses the grid-outage scenario (generator start probability, fuel
# endurance, load-shed order keeping the HP pump last, service continuity, asset
# criticality) and routes a recommendation through the EXISTING recommendation +
# audit path (pending, no control write); executive AGGREGATES ESTIMATED benefits
# from the existing layers into a value summary + pilot ROI. Every saving / ROI /
# avoided-cost figure is ESTIMATED and preliminary on a SYNTHETIC basis -- never a
# validated saving or guaranteed outcome; the executive responses carry an
# explicit disclaimer. Nothing here writes to any control system.
# ---------------------------------------------------------------------------


def _value_envelope(payload: dict, provenance: DataProvenance) -> dict:
    """Attach the read-only control boundary + provenance to a value response."""
    return {
        **payload,
        "facility_id": wq.FACILITY_ID,
        "train_id": wq.TRAIN_ID,
        "provenance": provenance.value,
        "control_boundary": ControlBoundary().model_dump(),
    }


class EnergyOptimizeRequest(BaseModel):
    fouling: Optional[float] = None


class GridOutageRequest(BaseModel):
    fuel_level_fraction: Optional[float] = None
    battery_bridge_minutes: Optional[float] = None


@app.get("/api/v1/energy/summary", dependencies=FEAT_ENERGY)
def energy_summary(fouling: Optional[float] = None) -> dict:
    """Energy-by-asset + current-vs-optimal specific-energy summary (estimated)."""
    return _value_envelope(
        energy.energy_summary(_wq_fouling(fouling)), DataProvenance.estimated
    )


@app.post("/api/v1/energy/optimize", dependencies=FEAT_ENERGY)
def energy_optimize(body: EnergyOptimizeRequest | None = None) -> dict:
    """Optimal HP-pump setpoint + ESTIMATED savings (constrained RO optimisation)."""
    fouling = _wq_fouling(body.fouling if body else None)
    result = energy.optimization_result(fouling)
    return _value_envelope(
        {"optimization": result.model_dump(mode="json")}, DataProvenance.estimated
    )


@app.get("/api/v1/energy/losses", dependencies=FEAT_ENERGY)
def energy_losses(fouling: Optional[float] = None) -> dict:
    """Avoidable specific-energy losses (estimated, synthetic basis)."""
    losses = energy.losses(_wq_fouling(fouling))
    return _value_envelope(
        {"losses": [loss.model_dump(mode="json") for loss in losses]},
        DataProvenance.estimated,
    )


@app.get("/api/v1/resilience/criticality", dependencies=FEAT_RESILIENCE)
def resilience_criticality() -> dict:
    """Resilience-criticality ranking of assets (highest impact/risk first)."""
    ranking = resil.criticality_ranking()
    return _value_envelope(
        {"criticality": [c.model_dump(mode="json") for c in ranking]},
        DataProvenance.preliminary,
    )


@app.get("/api/v1/resilience/generator", dependencies=FEAT_RESILIENCE)
def resilience_generator() -> dict:
    """Preliminary standby-generator start probability + fuel endurance."""
    gen = resil.generator_status()
    return _value_envelope(
        {"generator": gen.model_dump(mode="json")}, DataProvenance.preliminary
    )


def _route_resilience_recommendation(card, actor: str = "system") -> None:
    """Route the grid-outage recommendation through the existing recommendation +
    audit path (pending, operator approval required, no control write). Idempotent
    by its deterministic id so repeated assessments do not duplicate the card or
    reset an operator's decision."""
    if reco_store.get(card.recommendation_id) is not None:
        return
    reco_store.put(card)
    store.save_recommendation(
        card.recommendation_id,
        card.model_dump(mode="json"),
        facility_id=card.facility_id,
        train_id=card.train_id,
        status=card.approval_status.value,
    )
    store.audit(
        "resilience.recommendation.created",
        payload={"recommendation_id": card.recommendation_id, "asset_id": card.asset_id},
        actor=actor,
        subject=card.recommendation_id,
    )


@app.post("/api/v1/resilience/grid-outage", dependencies=FEAT_RESILIENCE)
def resilience_grid_outage(
    body: GridOutageRequest | None = None,
    user: Principal = Depends(get_current_user),
) -> dict:
    """Assess the grid-outage scenario: generator, shed plan, continuity, ranking.

    Routes the resulting generator-priority recommendation through the existing
    recommendation + audit path (pending, operator approval required, no control
    write).
    """
    fuel = body.fuel_level_fraction if body else None
    bridge = body.battery_bridge_minutes if body else None
    assessment = resil.assess_grid_outage(
        fuel_level_fraction=fuel, battery_bridge_minutes=bridge
    )
    card = assessment["recommendation"]
    _route_resilience_recommendation(card, actor=_actor(user))
    stored = reco_store.get(card.recommendation_id)
    return _value_envelope(
        {
            "scenario": assessment["scenario"],
            "generator": assessment["generator"].model_dump(mode="json"),
            "load_shed_plan": assessment["load_shed_plan"].model_dump(mode="json"),
            "service_continuity": assessment["service_continuity"].model_dump(mode="json"),
            "criticality": [c.model_dump(mode="json") for c in assessment["criticality"]],
            "recommendation": (stored or card).model_dump(mode="json"),
        },
        DataProvenance.preliminary,
    )


@app.get("/api/v1/executive/value-summary", dependencies=FEAT_EXECUTIVE)
def executive_value_summary(fouling: Optional[float] = None) -> dict:
    """Aggregated ESTIMATED value summary (illustrative, synthetic basis)."""
    summary = executive.value_summary(_wq_fouling(fouling))
    return _value_envelope(
        {"value_summary": summary.model_dump(mode="json"), "disclaimer": summary.disclaimer},
        DataProvenance.estimated,
    )


@app.get("/api/v1/executive/roi", dependencies=FEAT_EXECUTIVE)
def executive_roi(fouling: Optional[float] = None) -> dict:
    """Illustrative pilot ROI, annualized benefit + payback (ESTIMATED)."""
    estimate = executive.roi(_wq_fouling(fouling))
    return _value_envelope(
        {"roi": estimate.model_dump(mode="json"), "disclaimer": estimate.disclaimer},
        DataProvenance.estimated,
    )


# ---------------------------------------------------------------------------
# S3M Operations Assistant (advisory, read-only)
#
# A grounded natural-language interface over everything the platform computes.
# The assistant AGGREGATES existing layer outputs (health / anomaly / root-cause
# / water-quality / equipment / membrane / PdM / energy / resilience) plus
# retrieved seeded documents, assembles a WaterTwinPacket and routes it through
# the EXISTING s3m_connector (local grounded fallback preserved). It NEVER
# answers operational questions from general model knowledge. Every response
# carries the control boundary + a full evidence block; any recommended action
# routes through the existing recommendation + audit path (pending, no control
# write) and every question is audited.
# ---------------------------------------------------------------------------


def get_s3m_connector():
    """Return the injected connector (tests) or the process-wide default."""
    conn = getattr(app.state, "s3m_connector", None)
    if conn is None:
        from .s3m_connector import get_connector

        conn = get_connector()
    return conn


class AssistantAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    requested_by: Optional[str] = None


def _route_assistant_recommendation(card) -> None:
    """Route an assistant recommendation through the existing recommendation +
    audit path (pending, operator approval required, no control write). Idempotent
    by the deterministic assistant id so repeated asks do not duplicate a card or
    reset an operator's decision."""
    if card is None or reco_store.get(card.recommendation_id) is not None:
        return
    reco_store.put(card)
    store.save_recommendation(
        card.recommendation_id,
        card.model_dump(mode="json"),
        facility_id=card.facility_id,
        train_id=card.train_id,
        status=card.approval_status.value,
    )
    store.audit(
        "assistant.recommendation.created",
        payload={"recommendation_id": card.recommendation_id, "asset_id": card.asset_id},
        subject=card.recommendation_id,
    )


@app.post("/api/v1/assistant/ask", dependencies=FEAT_ASSISTANT)
def assistant_ask(body: AssistantAskRequest) -> dict:
    """Answer an operator question with a grounded, evidence-backed response.

    The answer is assembled from platform layer outputs + retrieved documents and
    routed through the S3M-Core connector (grounded local fallback preserved).
    Any recommended action is persisted ``pending`` through the existing
    recommendation + audit path; the question itself is always audited.
    """
    response = assistant.answer(
        body.question,
        requested_by=body.requested_by,
        connector=get_s3m_connector(),
    )
    _route_assistant_recommendation(response.recommended_action)
    store.audit(
        "assistant.ask",
        payload={
            "intent": response.intent,
            "target": response.target,
            "source_engine_status": response.source_engine_status,
            "documents_reviewed": response.evidence.documents_reviewed,
            "assets_reviewed": response.evidence.assets_reviewed,
        },
        actor=body.requested_by or "operator",
        subject=response.packet_id or response.intent,
    )
    return response.model_dump(mode="json")


@app.get("/api/v1/assistant/examples", dependencies=FEAT_ASSISTANT)
def assistant_examples() -> dict:
    """Return the canonical example questions (one per supported intent)."""
    return {
        "examples": assistant.EXAMPLE_QUESTIONS,
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get("/api/v1/documents")
def list_documents() -> dict:
    """List the seeded operations documents available for retrieval."""
    return {
        "documents": [d.model_dump(mode="json") for d in documents.list_documents()],
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get("/api/v1/documents/{document_id}")
def get_document(document_id: str) -> dict:
    """Return a single seeded document (metadata + full body)."""
    doc = documents.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"unknown document: {document_id}")
    return {**doc, "control_boundary": ControlBoundary().model_dump()}


@app.post("/api/v1/reset")
def reset(user: Principal = Depends(require_role("engineer"))) -> dict:
    """Clear cached runs, recommendations, and audit trail (demo convenience).

    Resetting demo state is an engineer/admin action (RBAC matrix).
    """
    with _runs_lock:
        _runs.clear()
    reco_store.clear()
    store.reset()
    meter.reset()
    store.audit("system.reset", actor=_actor(user), subject="watertwin-api")
    return {"status": "reset", "control_boundary": ControlBoundary().model_dump()}


@app.post("/api/v1/reports/scenario/{job_id}")
def scenario_report(
    job_id: str,
    user: Principal = Depends(get_current_user),
) -> PlainTextResponse:
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
        actor=_actor(user),
        subject=job_id,
    )
    filename = f"scenario-report-{job_id}.md"
    return PlainTextResponse(
        content=document,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Administration (admin-only): licensing/entitlements, usage metering + billing
# export, the signed-update channel reference, and support-bundle generation.
#
# These are commercial-hardening capabilities. None of them is a control path
# and none can relax the advisory/read-only safety invariant: feature-gating
# only hides advisory features by plan, metering is advisory bookkeeping, the
# update channel only verifies (never applies) a signed manifest, and support
# bundles are read-only, secret-redacted diagnostics. Every response still
# carries the control boundary; the CI boundary guard remains in force.
# ---------------------------------------------------------------------------


def _admin_health_snapshot() -> dict:
    """A lightweight, network-free health snapshot for support bundles."""
    cb = ControlBoundary()
    try:
        telemetry = get_source_resolution().describe()
    except Exception:  # pragma: no cover - resolver never raises
        telemetry = {}
    return {
        "service": config.SERVICE_NAME,
        "version": config.SERVICE_VERSION,
        "status": "healthy",
        "db_connected": store.db_connected,
        "telemetry_source": telemetry.get("active_source"),
        "auth_mode": "dev-bypass" if auth.auth_disabled() else "enforced",
        "control_boundary": cb.model_dump(),
    }


@app.get("/api/v1/admin/entitlements", dependencies=[Depends(require_role("admin"))])
def admin_entitlements() -> dict:
    """The tenant's licensing entitlement, plan features, and usage vs. limits."""
    ent = licensing.current_entitlements()
    usage = meter.snapshot()
    return {
        "entitlements": ent.describe(),
        "usage": usage,
        "limits_status": ent.limits_status(usage),
        # Explicit, machine-checkable assurance that feature-gating leaves the
        # advisory/read-only invariant untouched.
        "safety_invariant_intact": licensing.safety_invariant_intact(),
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get("/api/v1/admin/metering/usage", dependencies=[Depends(require_role("admin"))])
def admin_metering_usage() -> dict:
    """Current billing-period usage counts (facilities, assets, ingest volume)."""
    return {
        "usage": meter.snapshot(),
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get(
    "/api/v1/admin/metering/billing-export",
    dependencies=[Depends(require_role("admin"))],
)
def admin_metering_billing_export() -> dict:
    """Render a billing export of metered usage against the plan limits."""
    ent = licensing.current_entitlements()
    return {
        "billing_export": meter.billing_export(
            tenant_id=ent.tenant_id, plan=ent.plan, limits=ent.limits
        ),
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get("/api/v1/admin/update-channel", dependencies=[Depends(require_role("admin"))])
def admin_update_channel() -> dict:
    """Report the signed-update channel status (verify-before-apply; no auto-update)."""
    return {
        "update_channel": updates.channel_info(),
        "control_boundary": ControlBoundary().model_dump(),
    }


class UpdateVerifyRequest(BaseModel):
    #: The update manifest as a JSON object (signed with the release key).
    manifest: dict[str, Any]
    #: Hex-encoded Ed25519 signature over the canonical manifest.
    signature: str
    #: Optional PEM public key to verify against (else the configured key).
    public_key: Optional[str] = None


@app.post(
    "/api/v1/admin/update-channel/verify",
    dependencies=[Depends(require_role("admin"))],
)
def admin_update_channel_verify(
    body: UpdateVerifyRequest,
    user: Principal = Depends(get_current_user),
) -> dict:
    """Verify a signed update manifest. NEVER applies the update.

    This is the *verify* half of "verify before apply". The service has no code
    path that downloads or applies an update; applying a verified release is an
    out-of-band, operator-driven redeploy (documented, not automated).
    """
    result = updates.verify_manifest(
        body.manifest, body.signature, key_pem=body.public_key
    )
    store.audit(
        "update.signature.verified",
        payload={
            "verified": result.get("verified"),
            "manifest_version": body.manifest.get("version"),
            "fingerprint": result.get("fingerprint"),
            "applied": False,
        },
        actor=_actor(user),
        subject=str(body.manifest.get("version") or "unknown"),
    )
    return {
        "verification": result,
        "applied": False,
        "note": (
            "Signature verification only. This service never applies an update; "
            "apply a verified release out-of-band via a redeploy."
        ),
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.post("/api/v1/admin/support/bundle", dependencies=[Depends(require_role("admin"))])
def admin_support_bundle(user: Principal = Depends(get_current_user)) -> Response:
    """Generate a redacted support bundle (logs + SBOM + config snapshot).

    Secrets are redacted: secret-named env values and URL credentials are
    masked, and every discovered secret literal is scrubbed from logs and audit
    payloads (see app/support.py). The bundle contains no control state.
    """
    ent = licensing.current_entitlements()
    data, manifest = support.build_support_bundle(
        entitlements=ent.describe(),
        usage=meter.snapshot(),
        health=_admin_health_snapshot(),
        audit_events=store.recent_audit(200),
        config_env=dict(os.environ),
        log_lines=log_buffer.recent_lines(),
        sbom_dir=config.SBOM_DIR,
    )
    store.audit(
        "support.bundle.generated",
        payload={
            "bytes": len(data),
            "files": len(manifest.get("contents", [])),
            "secret_values_scrubbed": manifest.get("redaction", {}).get(
                "secret_values_scrubbed"
            ),
        },
        actor=_actor(user),
        subject="watertwin-api",
    )
    ts = manifest["generated_at"].replace(":", "").replace("-", "")
    filename = f"watertwin-support-bundle-{ts}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
