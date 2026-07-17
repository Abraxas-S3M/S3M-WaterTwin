"""watertwin-api: Simulation Center orchestration + recommendations.

Drives the hydraulic-sim service (read-only what-if), returns baseline-vs-scenario
comparisons for the dashboard Simulation Center, and produces recommendation cards
with the run's ``simulation_id`` attached to ``evidence.simulation_ids``.
"""

from __future__ import annotations

import math
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from canonical_water_model import (
    ApprovalStatus,
    ControlBoundary,
    DataProvenance,
    WorkOrderStatus,
    WQAlert,
)
from canonical_water_model import ControlBoundary, DataProvenance, WQAlert, now_iso
from canonical_water_model import ControlBoundary, DataProvenance, TelemetryReading, WQAlert

from simulation_contracts import ScenarioType, SimulationResult

from . import auth
from . import config
from . import deployment
from . import configuration
from . import events
from .auth import (
    WILDCARD,
    Principal,
    get_current_user,
    require_ingest,
    require_role,
)
from . import assistant
from . import condition
from . import compliance
from . import cmms as cmms_pkg
from . import documents
from . import energy
from . import executive
from . import licensing
from . import log_buffer
from .metering import meter
from . import maintenance
from . import facilities as facilities_mod
from . import membrane
from . import model_registry
from . import models as d1_models
from . import predictive_maintenance as pdm
from . import resilience as resil
from . import security as security_analytics
from . import siem_export
from . import sources
from . import support
from . import updates
from . import training
from . import water_quality as wq
from .config_store import ConfigStore
from .tag_normalization import RawReading, TagMap, TagMapError, load_tag_map, normalize
from .hydraulic_client import HydraulicSimClient, HydraulicSimError
from .network_store import NetworkStore
from .network_twin import NetworkTwin
from .recommendations import RecommendationStore, build_recommendation
from .reports import build_compliance_report, build_scenario_report
from .store import Store

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Log whether auth is enforced or bypassed (explicit dev mode) at startup.
    auth.log_auth_mode()
    # Enforce the deployment profile: under one_way_diode any platform->OT
    # request path is disabled (fail-closed). Raises if the configured telemetry
    # source would have the platform initiate a connection toward the OT zone,
    # preventing the service from starting in a one-way-breaking configuration.
    deployment.enforce_startup(config)
    # Bring the advisory event bus online (connects to NATS when configured,
    # otherwise degrades to direct in-process delivery). Then publish the
    # active telemetry configuration as a config-published event.
    events.get_bus()
    _publish_active_config()
    yield


def _publish_active_config() -> None:
    """Publish the currently active telemetry config (config-published event)."""
    try:
        telemetry = get_source_resolution().describe()
        events.publish_config_published(
            active_source=telemetry.get("active_source"),
            requested_source=telemetry.get("requested_source"),
            tag_map=config.OT_TAG_MAP,
            fallback=bool(telemetry.get("fallback")),
        )
    except Exception:  # pragma: no cover - startup publish is best-effort
        pass


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

# Configure structured JSON logging early so even import-time startup logs (the
# auth-mode banner below) are emitted as JSON. The full observability wiring
# (metrics, middleware, tracing) is completed further down once the store and
# telemetry-source dependencies exist; configure_logging is idempotent.
from watertwin_observability import configure_logging  # noqa: E402

configure_logging(config.SERVICE_NAME)

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
FEAT_PREDICTIVE_MAINTENANCE = licensing.authed_feature(licensing.FEATURE_PREDICTIVE_MAINTENANCE)
FEAT_ENERGY = licensing.authed_feature(licensing.FEATURE_ENERGY_OPTIMIZATION)
FEAT_RESILIENCE = licensing.authed_feature(licensing.FEATURE_RESILIENCE)
FEAT_EXECUTIVE = licensing.authed_feature(licensing.FEATURE_EXECUTIVE_VALUE)
FEAT_ASSISTANT = licensing.authed_feature(licensing.FEATURE_OPERATIONS_ASSISTANT)


@dataclass(frozen=True)
class Scope:
    """The tenant/facility a request is operating within.

    Resolved from the ``tenant_id`` / ``facility_id`` query parameters (falling
    back to the platform defaults for legacy single-facility callers) and only
    ever returned once the authenticated principal's membership has been checked.
    """

    tenant_id: str
    facility_id: str


def facility_scope(
    tenant_id: Optional[str] = Query(
        default=None, description="Tenant to scope this request to (defaults to the platform tenant)."
    ),
    facility_id: Optional[str] = Query(
        default=None, description="Facility to scope this request to (defaults to the platform facility)."
    ),
    user: Principal = Depends(get_current_user),
) -> Scope:
    """Authenticate, resolve the target tenant/facility, and enforce membership.

    Row-level scoping is enforced here, at the API layer: a principal may only
    read within a tenant/facility carried in its token, so cross-tenant access is
    denied (403) before any store query runs. Callers with no explicit
    tenant/facility membership (dev bypass, legacy single-facility tokens)
    resolve to the platform default scope and keep working unchanged.
    """
    resolved_tenant = tenant_id or config.DEFAULT_TENANT_ID
    resolved_facility = facility_id or config.DEFAULT_FACILITY_ID
    if not user.can_access(resolved_tenant, resolved_facility):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "cross-tenant access denied: caller is not a member of "
                f"tenant '{resolved_tenant}' / facility '{resolved_facility}'"
            ),
        )
    return Scope(tenant_id=resolved_tenant, facility_id=resolved_facility)


def _actor(user: Principal, fallback: str | None = None) -> str:
    """Audit actor for an action.

    When auth is enforced the authenticated identity is authoritative (a
    client-supplied actor is never trusted). Under the dev bypass we preserve
    the legacy behaviour of honouring an explicit fallback actor when provided.
    """
    if auth.auth_disabled() and fallback:
        return fallback
    return user.actor


def _can_see(user: Principal, tenant_id: Optional[str], facility_id: Optional[str]) -> bool:
    """True when ``user`` may read a record scoped to this tenant/facility.

    Facility-agnostic records (no ``facility_id``) are visible to any member of
    the tenant. This is the authoritative row-level visibility check for the
    audit + recommendation (config) read paths.
    """
    tenant = tenant_id or config.DEFAULT_TENANT_ID
    if not user.can_access_tenant(tenant):
        return False
    if facility_id is not None and not user.can_access_facility(facility_id):
        return False
    return True


def _store_tenant_filter(user: Principal, tenant_id: Optional[str]) -> Optional[str]:
    """Resolve the tenant to push down into the store for a scoped read.

    An explicit ``tenant_id`` (already access-checked by the caller) wins;
    otherwise a single-tenant principal is confined to its tenant, while a
    wildcard/multi-tenant principal reads unrestricted (``None``) and relies on
    :func:`_can_see` for per-row filtering.
    """
    if tenant_id is not None:
        return tenant_id
    if WILDCARD in user.tenants:
        return None
    if len(user.tenants) == 1:
        return next(iter(user.tenants))
    return None


def _apply_scope(card: Any, scope: Optional[Scope]) -> Any:
    """Stamp a recommendation card with the request's tenant/facility scope.

    Keeps every persisted advisory record row-scoped so it is only ever visible
    to the tenant/facility it belongs to. When no explicit scope is supplied the
    card keeps its canonical default tenant/facility.
    """
    if scope is not None:
        card.tenant_id = scope.tenant_id
        card.facility_id = scope.facility_id
    return card


reco_store = RecommendationStore(config.RECOMMENDATION_STORE_PATH)
work_order_store = maintenance.WorkOrderStore(config.WORK_ORDER_STORE_PATH)
store = Store(config.DATABASE_URL)
# The store fires the advisory ``audit-appended`` event after every successful
# append. The hook resolves the bus lazily so tests can inject their own bus.
store = Store(config.DATABASE_URL, event_sink=events.audit_event_sink)

# Operator Training Simulator sessions + records (SIMULATION only). Held in
# memory; the training sandbox has no control-write path (see app.training).
training_store = training.TrainingStore()


def get_cmms_adapter() -> cmms_pkg.CmmsAdapter:
    """Return the injected CMMS adapter (tests) or the config-resolved default."""
    adapter = getattr(app.state, "cmms_adapter", None)
    if adapter is None:
        adapter = cmms_pkg.resolve_cmms_adapter(config)
        app.state.cmms_adapter = adapter
    return adapter

# A1 config store: configurable per-parameter regulatory compliance limits.
# Deployment-configurable (env file / inline JSON); advisory-only, never a
# control-write path.
config_store = ConfigStore()

# Geospatial network twin: PostGIS-backed spatial store (in-memory/GeoJSON
# fallback) plus the imported topology (shared with hydraulic-sim). Advisory,
# read-only, synthetic coordinates only.
network_store = NetworkStore(config.DATABASE_URL)
network_twin = NetworkTwin(network_store)

# Versioned, approval-gated customer configuration service. It shares the single
# ``store`` instance so every configuration state change is appended to the same
# tamper-evident audit hash chain surfaced by /api/v1/audit. Configuration is
# declarative data only and never touches a control path.
config_service = configuration.init_app(app, store)

# Completed runs cached by simulation job id so a downloadable report can be
# regenerated on demand. Advisory, read-only what-if data only.
_runs: dict[str, dict[str, Any]] = {}
_runs_lock = threading.RLock()

# Latest telemetry pushed in by edge gateways, keyed by (asset_id, metric). This
# is an observability mirror of the newest reading per signal (advisory data
# only); it is never a control-write path. Bounded by the number of distinct
# signals, cleared by the demo reset.
_latest_telemetry: dict[tuple[str, str], dict[str, Any]] = {}
_latest_telemetry_lock = threading.RLock()
# Last-seen state per gateway (source health + counters) for observability.
_gateway_state: dict[str, dict[str, Any]] = {}


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


# Observability: structured JSON logging, correlation ids, Prometheus metrics
# (+ /metrics) and OpenTelemetry traces. Registers scrape-time callbacks for the
# audit-chain length, recommendation buffer depth and telemetry ingest lag.
from . import observability  # noqa: E402

observability.setup(
    app,
    store=store,
    reco_store=reco_store,
    get_source_resolution=get_source_resolution,
)


class SimulationCenterRequest(BaseModel):
    scenario: ScenarioType
    parameters: dict[str, Any] = Field(default_factory=dict)
    create_recommendation: bool = True
    tenant_id: str = config.DEFAULT_TENANT_ID
    facility_id: str = config.DEFAULT_FACILITY_ID
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
        "network_twin": network_store.describe(),
        "telemetry_source": telemetry.get("active_source"),
        "telemetry_source_requested": telemetry.get("requested_source"),
        "telemetry_source_fallback": telemetry.get("fallback"),
        "telemetry": telemetry,
        "deployment_profile": deployment.get_profile(config),
        "platform_to_ot_enabled": not deployment.is_one_way_diode(config),
        "event_bus": events.get_bus().status(),
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


# ---------------------------------------------------------------------------
# Geospatial Network Twin (advisory, read-only)
#
# A geo-referenced digital twin of the water-distribution network, imported from
# the same EPANET model the hydraulic simulation runs (shared topology). It
# models pipes/nodes/junctions/valves/pumps/tanks/reservoirs with GeoJSON
# geometry linked to canonical asset ids, persisted in PostGIS when available
# (in-memory/GeoJSON fallback otherwise). Endpoints serve GeoJSON feature
# collections, per-asset spatial lookup, nearest-element lookup, and an
# EPANET-residual leak-localization overlay that REUSES the hydraulic-sim
# residual ranking. Coordinates are SYNTHETIC and overlays are PRELIMINARY;
# nothing here writes to any control system.
# ---------------------------------------------------------------------------

_NETWORK_ELEMENT_TYPES = {
    "junction",
    "reservoir",
    "tank",
    "pipe",
    "pump",
    "valve",
}
_NETWORK_KINDS = {"node", "link"}


@app.get("/api/v1/network/", dependencies=AUTHENTICATED)
def network_twin_info() -> dict:
    """Describe the geospatial network twin (topology + storage + boundary)."""
    network_twin.ensure_loaded()
    return {
        **network_twin.topology.metadata,
        "storage": network_store.describe(),
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get("/api/v1/network/features", dependencies=AUTHENTICATED)
def network_features(
    element_type: Optional[str] = None,
    kind: Optional[str] = None,
) -> dict:
    """Return the network twin as a GeoJSON FeatureCollection.

    Optional filters: ``element_type`` (junction/reservoir/tank/pipe/pump/valve)
    and ``kind`` (node/link).
    """
    if element_type is not None and element_type not in _NETWORK_ELEMENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"element_type must be one of {sorted(_NETWORK_ELEMENT_TYPES)}",
        )
    if kind is not None and kind not in _NETWORK_KINDS:
        raise HTTPException(
            status_code=422, detail=f"kind must be one of {sorted(_NETWORK_KINDS)}"
        )
    return network_twin.feature_collection(element_type=element_type, kind=kind)


@app.get("/api/v1/network/assets/{asset_id}", dependencies=AUTHENTICATED)
def network_asset(asset_id: str) -> dict:
    """Spatial lookup for a single asset (canonical asset id or element id)."""
    fc = network_twin.asset_features(asset_id)
    if not fc["features"]:
        raise HTTPException(
            status_code=404, detail=f"no network element for asset '{asset_id}'"
        )
    return fc


@app.get("/api/v1/network/nearest", dependencies=AUTHENTICATED)
def network_nearest(lon: float, lat: float, limit: int = 1) -> dict:
    """Return the nearest network element(s) to a WGS84 ``(lon, lat)`` point."""
    limit = max(1, min(limit, 50))
    return network_twin.nearest(lon, lat, limit=limit)


@app.get("/api/v1/network/overlays/leak-localization", dependencies=AUTHENTICATED)
def network_leak_overlay(
    node_id: str = "J-D2",
    area_m2: float = 0.01,
    discharge_coeff: float = 0.75,
) -> dict:
    """EPANET-residual leak-localization overlay (preliminary + synthetic).

    Runs the leak what-if via hydraulic-sim and translates its pressure-residual
    ranking into geospatial candidate zones. The overlay reuses the simulation's
    residual output and is advisory only -- never a validated leak location.
    """
    client = get_hydraulic_client()
    try:
        result = client.run(
            ScenarioType.leak,
            parameters={
                "node_id": node_id,
                "area_m2": area_m2,
                "discharge_coeff": discharge_coeff,
            },
        )
    except HydraulicSimError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return network_twin.leak_overlay(result)


@app.post("/api/v1/simulation-center/run")
def run_scenario(
    request: SimulationCenterRequest,
    user: Principal = Depends(require_role("engineer")),
) -> dict:
    """Run baseline + scenario and (optionally) create a recommendation.

    Running a what-if scenario is an engineer/admin action (RBAC matrix), and is
    confined to the caller's tenant/facility membership.
    """
    # Usage metering (billing export): count the facility and the run.
    meter.record_facility(request.facility_id)
    meter.record_api_call("scenario_run")
    if not user.can_access(request.tenant_id, request.facility_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "cross-tenant access denied: caller is not a member of "
                f"tenant '{request.tenant_id}' / facility '{request.facility_id}'"
            ),
        )
    scope = Scope(tenant_id=request.tenant_id, facility_id=request.facility_id)
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
        _apply_scope(card, scope)
        reco_store.put(card)
        recommendation = card.model_dump(mode="json")
        store.save_recommendation(
            card.recommendation_id,
            recommendation,
            tenant_id=card.tenant_id,
            facility_id=card.facility_id,
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
            tenant_id=scope.tenant_id,
            facility_id=scope.facility_id,
        )

    run = {
        "scenario": request.scenario.value,
        "tenant_id": request.tenant_id,
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
        tenant_id=scope.tenant_id,
        facility_id=scope.facility_id,
    )
    return run


@app.get("/api/v1/recommendations")
def list_recommendations(
    tenant_id: Optional[str] = Query(default=None),
    facility_id: Optional[str] = Query(default=None),
    user: Principal = Depends(get_current_user),
) -> list[dict]:
    """List recommendation (config) records the caller is scoped to see.

    Row-level filtered by tenant/facility membership: a caller only ever sees the
    recommendations for tenants/facilities carried in its token.
    """
    if tenant_id is not None and not user.can_access_tenant(tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="unknown tenant")
    if facility_id is not None and not user.can_access_facility(facility_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="unknown facility")
    return [
        c.model_dump(mode="json")
        for c in reco_store.list()
        if _can_see(user, getattr(c, "tenant_id", None), getattr(c, "facility_id", None))
        and (tenant_id is None or (getattr(c, "tenant_id", None) or config.DEFAULT_TENANT_ID) == tenant_id)
        and (facility_id is None or getattr(c, "facility_id", None) == facility_id)
    ]


@app.get("/api/v1/recommendations/{recommendation_id}", dependencies=AUTHENTICATED)
def get_recommendation(
    recommendation_id: str, user: Principal = Depends(get_current_user)
) -> dict:
    card = reco_store.get(recommendation_id)
    # A cross-tenant record is reported as not-found so its existence never leaks.
    if card is None or not _can_see(
        user, getattr(card, "tenant_id", None), getattr(card, "facility_id", None)
    ):
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
    # A cross-tenant record is reported as not-found so its existence never leaks.
    if card is None or not _can_see(
        user, getattr(card, "tenant_id", None), getattr(card, "facility_id", None)
    ):
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
        tenant_id=getattr(card, "tenant_id", None),
        facility_id=getattr(card, "facility_id", None),
    )
    return card.model_dump(mode="json")


@app.get("/api/v1/audit")
def audit_log(
    limit: int = 100,
    tenant_id: Optional[str] = Query(default=None),
    facility_id: Optional[str] = Query(default=None),
    user: Principal = Depends(require_role("auditor")),
) -> dict:
    """Read the audit trail (auditor/admin role required), tenant/facility scoped.

    The trail is row-level scoped to the caller's tenant/facility membership so an
    auditor of one tenant can never read another tenant's audit events. An
    explicit ``tenant_id`` / ``facility_id`` narrows the view further (and must be
    within the caller's membership).
    """
    if tenant_id is not None and not user.can_access_tenant(tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="unknown tenant")
    if facility_id is not None and not user.can_access_facility(facility_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="unknown facility")
    events = store.recent_audit(
        limit,
        tenant_id=_store_tenant_filter(user, tenant_id),
        facility_id=facility_id,
    )
    events = [e for e in events if _can_see(user, e.get("tenant_id"), e.get("facility_id"))]
    return {"events": events}


# ---------------------------------------------------------------------------
# Multi-facility administration + fleet roll-up (advisory, read-only).
#
# Every response is scoped to the caller's tenant/entitlement so cross-tenant
# data is never returned. tenant-admins/admins see every facility in their
# tenant; facility-operators see only the facility (or facilities) assigned to
# them. No control-write path is introduced.
# ---------------------------------------------------------------------------


@app.get("/api/v1/facilities")
def facilities_list(user: Principal = Depends(get_current_user)) -> dict:
    """List the facilities visible to the caller (tenant-scoped)."""
    return facilities_mod.list_facilities(user)


@app.get("/api/v1/fleet/overview")
def fleet_overview(user: Principal = Depends(get_current_user)) -> dict:
    """Fleet roll-up (health/energy/alerts) across the caller's facilities."""
    return facilities_mod.fleet_overview(user)


@app.get("/api/v1/audit/verify", dependencies=[Depends(require_role("auditor"))])
def audit_verify() -> dict:
    """Verify the tamper-evident audit hash chain (auditor/admin role required).

    Re-walks the append-only chain and returns ``{"ok": true, ...}`` when every
    event's link and content hash are intact, or ``{"ok": false, "broken_at":
    <event id>, ...}`` identifying the first event that fails validation (e.g. a
    payload that was altered after the fact).
    """
    return store.verify_chain()


@app.get("/api/v1/events/status", dependencies=AUTHENTICATED)
def events_status() -> dict:
    """Report advisory event-bus state + metrics (degraded when NATS is down).

    The bus is advisory / notification only; it never carries a control command.
    ``degraded == true`` means events are being delivered directly in-process
    (fallback) because NATS is not configured or unreachable.
    """
    return {
        **events.get_bus().status(),
        "control_boundary": ControlBoundary().model_dump(),
    }


# ---------------------------------------------------------------------------
# Cyber-Physical Security (advisory, read-only)
#
# Surfaces the platform's EXISTING cyber-physical + anomaly signals as a security
# posture view for the ``security`` role: sensor-confidence scoring, cyber-
# physical consistency (observed telemetry vs. the plant's hydraulic/physical
# design expectation), telemetry source-health, and the tamper-evident audit
# hash-chain verify status. A SIEM export renders the immutable audit log as a
# signed, append-only JSON/CEF feed. Every response carries the read-only control
# boundary; nothing here writes to any control system (no control path).
# ---------------------------------------------------------------------------

SECURITY = [Depends(require_role("security"))]


def _security_reading_count(resolution: sources.SourceResolution) -> Optional[int]:
    """Best-effort count of the latest telemetry batch (never raises)."""
    try:
        return len(resolution.source.read_latest())
    except Exception:  # pragma: no cover - defensive; a live OT feed may be down
        return None


@app.get("/api/v1/security/overview", dependencies=SECURITY)
def security_overview() -> dict:
    """Cyber-physical security posture (security/admin role required).

    Aggregates sensor-confidence scoring, cyber-physical consistency detection
    (telemetry vs. hydraulic expectation), telemetry source-health and the audit
    hash-chain integrity status into a single read-only posture view.
    """
    resolution = get_source_resolution()
    consistency = security_analytics.cyber_physical_consistency()
    confidence = security_analytics.sensor_confidence(consistency)
    source = security_analytics.source_health(
        resolution, reading_count=_security_reading_count(resolution)
    )
    audit_status = store.verify_chain()
    status = security_analytics.overall_status(
        audit_ok=bool(audit_status.get("ok")),
        source_status=source.get("status", "unknown"),
        consistency=consistency,
        confidence=confidence,
    )
    return {
        "status": status,
        "sensor_confidence": confidence,
        "cyber_physical_consistency": consistency,
        "source_health": source,
        "audit_integrity": audit_status,
        "facility_id": wq.FACILITY_ID,
        "train_id": wq.TRAIN_ID,
        "provenance": DataProvenance.preliminary.value,
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get("/api/v1/security/siem-export")
def security_siem_export(
    format: str = "json",
    user: Principal = Depends(require_role("security")),
):
    """Signed, append-only SIEM export of the immutable audit log.

    ``format=json`` (default) returns the ordered chain + chain head + live
    verify status + a detached HMAC-SHA256 signature; ``format=cef`` returns one
    ArcSight CEF line per event (oldest-first) with a trailing signature line.
    Read-only: it snapshots and signs the audit trail and writes nothing to any
    control system.
    """
    fmt = (format or "json").strip().lower()
    if fmt not in {"json", "cef"}:
        raise HTTPException(status_code=422, detail="format must be 'json' or 'cef'")

    events = store.audit_chain_asc()
    verify_result = store.verify_chain()

    # Record that an export was taken (append-only; the snapshot above predates
    # this event, so the signed export is unaffected). Advisory action only.
    store.audit(
        "security.siem_export",
        payload={"format": fmt, "record_count": len(events)},
        actor=_actor(user),
        subject="audit-log",
    )

    if fmt == "cef":
        document = siem_export.build_cef_export(events, verify_result)
        return PlainTextResponse(
            content=document,
            media_type="text/plain",
            headers={
                "Content-Disposition": 'attachment; filename="watertwin-siem-export.cef"'
            },
        )
    return siem_export.build_json_export(events, verify_result)


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


class TelemetryIngestRequest(BaseModel):
    """A batch of canonical telemetry readings forwarded by an edge gateway.

    ``batch_id`` is the gateway's stable store-and-forward key; ingest is
    idempotent on it so replaying a durable spool after a crash never
    double-writes telemetry or the audit trail.
    """

    batch_id: str = Field(min_length=1, max_length=200)
    readings: list[TelemetryReading] = Field(default_factory=list)
    #: Optional producer label (e.g. gateway id / source), recorded for audit.
    source: Optional[str] = None


@app.get("/api/v1/ingestion/source", dependencies=AUTHENTICATED)
def ingestion_source() -> dict:
    """Report the active telemetry source and any fallback to synthetic."""
    resolution = get_source_resolution()
    return {
        **resolution.describe(),
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.post("/api/v1/ingestion/telemetry")
def ingest_telemetry(
    body: TelemetryIngestRequest,
    user: Principal = Depends(require_ingest),
) -> dict:
    """Ingest a batch of telemetry readings (edge store-and-forward destination).

    Persists the readings and appends a single ``telemetry.ingested`` event to
    the tamper-evident audit chain. Idempotent on ``batch_id`` (a replayed batch
    is a no-op), so an edge gateway that resends its durable spool after a crash
    recovers with no data loss and no duplication while the audit chain stays
    valid. This reads telemetry *into* the platform; it is never a control write.
    """
    if not body.readings:
        raise HTTPException(status_code=422, detail="a telemetry batch must contain readings")
    readings = [r.model_dump(mode="json") for r in body.readings]
    result = store.ingest_telemetry(
        body.batch_id,
        readings,
        actor=_actor(user, "edge-gateway"),
        source=body.source,
    )
    return {**result, "control_boundary": ControlBoundary().model_dump()}


@app.get("/api/v1/ingestion/telemetry/stats", dependencies=AUTHENTICATED)
def ingestion_telemetry_stats() -> dict:
    """Report telemetry ingest counters (distinct batches + total readings)."""
    return {**store.telemetry_stats(), "control_boundary": ControlBoundary().model_dump()}


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
    events.publish_telemetry_ingested(
        tag_map=tag_map.map_id,
        mapped=len(result.readings),
        rejected=len(result.rejected),
        total=len(raw),
    )
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
# Telemetry ingest (inbound sink for the outbound-only edge-gateway)
#
# The edge-gateway is an OUTBOUND-ONLY collector: it reads real OT feeds behind
# the plant firewall (strictly read-only), validates + normalizes them, buffers
# them in an encrypted local store-and-forward queue, and PUSHES canonical
# readings here. This endpoint is the API-side sink. Ingesting telemetry is an
# advisory data write only -- it records the newest reading per signal and
# audits the batch; it is NEVER a control-write path.
# ---------------------------------------------------------------------------


class TelemetryReadingInput(BaseModel):
    asset_id: str
    metric: str
    value: float
    unit: str
    timestamp: str
    provenance: str = "measured"
    #: Data-quality flag assigned by the gateway (e.g. ``good`` / ``stale`` /
    #: ``out_of_range`` / ``frozen``). Advisory only.
    quality: Optional[str] = None


class TelemetryIngestBatch(BaseModel):
    #: Stable identifier of the pushing gateway (for source-health tracking).
    gateway_id: str = Field(min_length=1, max_length=128)
    #: The active OT source the gateway is reading (synthetic/opcua/modbus/...).
    source: Optional[str] = None
    #: Whether the gateway is running on its synthetic fallback source.
    fallback: bool = False
    #: Gateway-reported source-health snapshot (advisory, opaque).
    source_health: Optional[dict[str, Any]] = None
    #: The gateway's send timestamp (ISO-8601).
    sent_at: Optional[str] = None
    readings: list[TelemetryReadingInput] = Field(default_factory=list)


@app.post("/api/v1/ingestion/telemetry")
def ingest_telemetry(
    batch: TelemetryIngestBatch,
    user: Principal = Depends(get_current_user),
) -> dict:
    """Accept a pushed batch of canonical telemetry from an edge gateway.

    Stores the newest reading per ``(asset_id, metric)`` for observability,
    records the gateway's source-health snapshot, and audits the ingest. This is
    advisory data only and never writes to any control system.
    """
    accepted = 0
    rejected: list[dict[str, Any]] = []
    now = now_iso()
    with _latest_telemetry_lock:
        for reading in batch.readings:
            if not math.isfinite(reading.value):
                rejected.append({"asset_id": reading.asset_id, "metric": reading.metric,
                                 "reason": "non-finite value"})
                continue
            _latest_telemetry[(reading.asset_id, reading.metric)] = {
                **reading.model_dump(mode="json"),
                "gateway_id": batch.gateway_id,
                "ingested_at": now,
            }
            accepted += 1
        _gateway_state[batch.gateway_id] = {
            "gateway_id": batch.gateway_id,
            "source": batch.source,
            "fallback": batch.fallback,
            "source_health": batch.source_health,
            "sent_at": batch.sent_at,
            "last_ingest_at": now,
            "last_batch_size": len(batch.readings),
            "last_accepted": accepted,
        }
    store.audit(
        "telemetry.ingested",
        payload={
            "gateway_id": batch.gateway_id,
            "source": batch.source,
            "fallback": batch.fallback,
            "accepted": accepted,
            "rejected": len(rejected),
        },
        actor=_actor(user, batch.gateway_id),
        subject=batch.gateway_id,
    )
    return {
        "status": "accepted",
        "accepted": accepted,
        "rejected": rejected,
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get("/api/v1/ingestion/telemetry/latest", dependencies=AUTHENTICATED)
def latest_telemetry() -> dict:
    """Return the newest pushed reading per signal + per-gateway source health."""
    with _latest_telemetry_lock:
        readings = list(_latest_telemetry.values())
        gateways = list(_gateway_state.values())
    return {
        "readings": readings,
        "gateways": gateways,
        "count": len(readings),
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


def _wq_envelope(
    payload: dict, provenance: DataProvenance, scope: Optional[Scope] = None
) -> dict:
    """Attach the read-only control boundary + provenance to every WQ response."""
    return {
        **payload,
        "tenant_id": scope.tenant_id if scope else config.DEFAULT_TENANT_ID,
        "facility_id": scope.facility_id if scope else wq.FACILITY_ID,
        "train_id": wq.TRAIN_ID,
        "provenance": provenance.value,
        "control_boundary": ControlBoundary().model_dump(),
    }


def _route_wq_alerts(
    alerts: list[WQAlert], actor: str = "system", scope: Optional[Scope] = None
) -> None:
    """Route WQ alerts through the existing recommendation + audit path.

    Each alert becomes a ``pending`` recommendation card (operator approval
    required, no control write). Idempotent by the alert-derived id so repeated
    polling does not duplicate cards or reset an operator's decision.
    """
    for alert in alerts:
        card = wq.build_wq_recommendation(alert)
        _apply_scope(card, scope)
        if reco_store.get(card.recommendation_id) is not None:
            continue
        reco_store.put(card)
        store.save_recommendation(
            card.recommendation_id,
            card.model_dump(mode="json"),
            tenant_id=card.tenant_id,
            facility_id=card.facility_id,
            train_id=card.train_id,
            status=card.approval_status.value,
        )
        store.audit(
            "wq.alert.created",
            payload={"recommendation_id": card.recommendation_id, "code": alert.code},
            actor=actor,
            subject=card.recommendation_id,
            tenant_id=card.tenant_id,
            facility_id=card.facility_id,
        )
        events.publish_alert_raised(
            code=alert.code,
            recommendation_id=card.recommendation_id,
            stage=(alert.stage.value if alert.stage else None),
            cause=alert.cause,
        )


@app.get("/api/v1/water-quality/status", dependencies=FEAT_WATER_QUALITY)
def water_quality_status(
    fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
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
        scope,
    )


@app.get("/api/v1/water-quality/contaminant-matrix", dependencies=FEAT_WATER_QUALITY)
def water_quality_contaminant_matrix(
    fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Contaminant concentration across the treatment path (intake -> brine)."""
    snap = wq.compute_snapshot(_wq_fouling(fouling))
    return _wq_envelope(
        {"rows": [r.model_dump(mode="json") for r in snap.contaminant_matrix]},
        DataProvenance.synthetic,
        scope,
    )


@app.get("/api/v1/water-quality/removal", dependencies=FEAT_WATER_QUALITY)
def water_quality_removal(
    fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Treatment removal: current vs design vs predicted (with confidence)."""
    snap = wq.compute_snapshot(_wq_fouling(fouling))
    return _wq_envelope({"removal": snap.removal}, DataProvenance.preliminary, scope)


@app.get("/api/v1/water-quality/scaling", dependencies=FEAT_WATER_QUALITY)
def water_quality_scaling(
    fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Per-compound scaling risk (preliminary)."""
    snap = wq.compute_snapshot(_wq_fouling(fouling))
    return _wq_envelope(
        {"scaling": [r.model_dump(mode="json") for r in snap.scaling]},
        DataProvenance.preliminary,
        scope,
    )


@app.get("/api/v1/water-quality/forecast", dependencies=FEAT_WATER_QUALITY)
def water_quality_forecast(
    fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Preliminary forecasts: salinity, boron, scaling, fouling (bounded)."""
    snap = wq.compute_snapshot(_wq_fouling(fouling))
    return _wq_envelope(
        {"forecasts": [f.model_dump(mode="json") for f in snap.forecasts]},
        DataProvenance.preliminary,
        scope,
    )


@app.get("/api/v1/water-quality/alerts", dependencies=FEAT_WATER_QUALITY)
def water_quality_alerts(
    fouling: Optional[float] = None,
    scope: Scope = Depends(facility_scope),
    user: Principal = Depends(get_current_user),
) -> dict:
    """WQ alerts; each is routed to the recommendation + audit path (pending)."""
    snap = wq.compute_snapshot(_wq_fouling(fouling))
    _route_wq_alerts(snap.alerts, actor=_actor(user), scope=scope)
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
        scope,
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


def _pdm_envelope(
    payload: dict,
    provenance: DataProvenance = DataProvenance.preliminary,
    scope: Optional[Scope] = None,
) -> dict:
    """Attach the read-only control boundary + provenance to every PdM response."""
    return {
        **payload,
        "tenant_id": scope.tenant_id if scope else config.DEFAULT_TENANT_ID,
        "facility_id": scope.facility_id if scope else wq.FACILITY_ID,
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
def equipment_health(
    asset_id: str, fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Transparent component health with a contribution breakdown."""
    _require_asset(asset_id)
    health = pdm.component_health_for(asset_id, _wq_fouling(fouling))
    return _pdm_envelope({"health": health.model_dump(mode="json")}, scope=scope)


@app.get("/api/v1/equipment/{asset_id}/rul", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def equipment_rul(
    asset_id: str, fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Preliminary remaining-useful-life with an uncertainty band."""
    _require_asset(asset_id)
    rul = pdm.rul_for(asset_id, _wq_fouling(fouling))
    return _pdm_envelope({"rul": rul.model_dump(mode="json")}, scope=scope)


@app.get("/api/v1/equipment/{asset_id}/failure-probability", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def equipment_failure_probability(
    asset_id: str, fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Preliminary failure probability over {24h, 7d, 30d, 90d} horizons."""
    _require_asset(asset_id)
    fp = pdm.failure_probability_for(asset_id, _wq_fouling(fouling))
    return _pdm_envelope({"failure_probability": fp.model_dump(mode="json")}, scope=scope)


@app.get("/api/v1/equipment/{asset_id}/envelope", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def equipment_envelope(asset_id: str, scope: Scope = Depends(facility_scope)) -> dict:
    """Operating-envelope regime fractions (BEP / low-flow / high-pressure / ...)."""
    _require_asset(asset_id)
    env = pdm.envelope_for(asset_id)
    return _pdm_envelope({"envelope": env.model_dump(mode="json")}, scope=scope)


@app.get("/api/v1/equipment/{asset_id}/root-cause", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def equipment_root_cause(asset_id: str, scope: Scope = Depends(facility_scope)) -> dict:
    """Causal root-cause ranking (probabilities sum to ~1.0)."""
    _require_asset(asset_id)
    rc = pdm.root_cause_for(asset_id)
    return _pdm_envelope({"root_cause": rc.model_dump(mode="json")}, scope=scope)


@app.get("/api/v1/membrane/{asset_id}/health", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def membrane_health(
    asset_id: str, fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Membrane fouling / scaling / health (reuses the Water Quality layer)."""
    _require_asset(asset_id)
    mh = membrane.compute_membrane_health(_wq_fouling(fouling), asset_id=asset_id)
    return _pdm_envelope({"membrane": mh.model_dump(mode="json")}, scope=scope)


def _route_pdm_recommendations(
    cards: list, actor: str = "system", scope: Optional[Scope] = None
) -> None:
    """Route PdM recommendation cards through the existing recommendation + audit
    path. Each card is created ``pending`` (operator approval required, no
    control write) and is idempotent by its asset-derived id so repeated polling
    does not duplicate cards or reset an operator's decision."""
    for card in cards:
        _apply_scope(card, scope)
        if reco_store.get(card.recommendation_id) is not None:
            continue
        reco_store.put(card)
        store.save_recommendation(
            card.recommendation_id,
            card.model_dump(mode="json"),
            tenant_id=card.tenant_id,
            facility_id=card.facility_id,
            train_id=card.train_id,
            status=card.approval_status.value,
        )
        store.audit(
            "pdm.recommendation.created",
            payload={"recommendation_id": card.recommendation_id, "asset_id": card.asset_id},
            actor=actor,
            subject=card.recommendation_id,
            tenant_id=card.tenant_id,
            facility_id=card.facility_id,
        )
        events.publish_workorder_created(
            recommendation_id=card.recommendation_id, asset_id=card.asset_id
        )


@app.get("/api/v1/maintenance/ranking", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def maintenance_ranking(
    fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Risk-ranked predictive-maintenance view across all critical assets."""
    ranking = pdm.compute_ranking(_wq_fouling(fouling))
    return _pdm_envelope({"ranking": [p.model_dump(mode="json") for p in ranking]}, scope=scope)


@app.get("/api/v1/maintenance/recommendations", dependencies=FEAT_PREDICTIVE_MAINTENANCE)
def maintenance_recommendations(
    fouling: Optional[float] = None,
    scope: Scope = Depends(facility_scope),
    user: Principal = Depends(get_current_user),
) -> dict:
    """PdM recommendations; each routes to the recommendation + audit path (pending)."""
    recs = pdm.compute_recommendations(_wq_fouling(fouling))
    cards = [pdm.build_pdm_card(rec) for rec in recs]
    _route_pdm_recommendations(cards, actor=_actor(user), scope=scope)
    return _pdm_envelope(
        {
            "recommendations": [p.model_dump(mode="json") for p in recs],
            "cards": [
                reco_store.get(rec.recommendation_id).model_dump(mode="json")
                for rec in recs
                if rec.recommendation_id
                and reco_store.get(rec.recommendation_id) is not None
            ],
        },
        scope=scope,
    )


# ---------------------------------------------------------------------------
# D1 analytics models (advisory, read-only)
#
# Three D1-framework models -- HP-pump condition, membrane fouling & salt passage,
# and cartridge-filter replacement -- each with full ModelSpec metadata, a
# synthetic back-test dataset, preliminary (pending-calibration) alert thresholds,
# a drift hook and a benchmark scaffold. Every model REUSES existing canonical
# physics / service layers (nothing duplicated). Every response carries the
# read-only control boundary + provenance; thresholds are preliminary pending
# customer calibration; nothing here writes to any control system.
# ---------------------------------------------------------------------------


def _models_envelope(payload: dict, provenance: DataProvenance = DataProvenance.preliminary) -> dict:
    """Attach the read-only control boundary + provenance to a model response."""
    return {
        **payload,
        "facility_id": wq.FACILITY_ID,
        "train_id": wq.TRAIN_ID,
        "provenance": provenance.value,
        "control_boundary": ControlBoundary().model_dump(),
    }


def _require_model(model_id: str):
    if model_id not in d1_models.MODELS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown model: {model_id}; known: {d1_models.list_model_ids()}",
        )
    return d1_models.get_adapter(model_id)


class ModelAssessmentRequest(BaseModel):
    inputs: dict[str, float] = Field(default_factory=dict)


@app.get("/api/v1/models", dependencies=AUTHENTICATED)
def list_models() -> dict:
    """List the registered D1 models with their spec summaries."""
    return _models_envelope(
        {
            "models": [
                {
                    "model_id": ad.spec.model_id,
                    "name": ad.spec.name,
                    "version": ad.spec.version,
                    "tier": ad.spec.tier.value,
                    "asset_type": ad.spec.asset_type,
                    "target": ad.spec.target,
                    "status": ad.spec.status,
                }
                for ad in d1_models.MODELS.values()
            ]
        }
    )


@app.get("/api/v1/models/{model_id}/spec", dependencies=AUTHENTICATED)
def model_spec(model_id: str) -> dict:
    """Full ModelSpec metadata (inputs, outputs, baseline, reused components,
    preliminary thresholds, drift + calibration configuration)."""
    adapter = _require_model(model_id)
    return _models_envelope({"spec": adapter.spec.model_dump(mode="json")})


@app.get("/api/v1/models/{model_id}/assessment", dependencies=AUTHENTICATED)
def model_assessment(model_id: str, fouling: Optional[float] = None) -> dict:
    """Reference advisory assessment for the model's asset (read-only).

    ``fouling`` is an optional what-if severity honoured by the membrane model.
    """
    adapter = _require_model(model_id)
    inputs: dict[str, float] = {} if fouling is None else {"fouling": _wq_fouling(fouling)}
    assessment = adapter.assess(inputs)
    return _models_envelope({"assessment": assessment.model_dump(mode="json")})


@app.post("/api/v1/models/{model_id}/assessment", dependencies=AUTHENTICATED)
def model_assessment_post(model_id: str, body: ModelAssessmentRequest | None = None) -> dict:
    """Advisory assessment for arbitrary (read-only) model inputs."""
    adapter = _require_model(model_id)
    assessment = adapter.assess(body.inputs if body else {})
    return _models_envelope({"assessment": assessment.model_dump(mode="json")})


@app.get("/api/v1/models/{model_id}/backtest", dependencies=AUTHENTICATED)
def model_backtest(model_id: str, threshold: Optional[float] = None) -> dict:
    """Back-test metrics from the D1 harness (preliminary, synthetic dataset)."""
    adapter = _require_model(model_id)
    metrics = adapter.backtest(threshold)
    return _models_envelope({"backtest": metrics.model_dump(mode="json")})


@app.get("/api/v1/models/{model_id}/benchmark", dependencies=AUTHENTICATED)
def model_benchmark(model_id: str) -> dict:
    """Preliminary benchmark scaffold (back-test + Brier + drift)."""
    adapter = _require_model(model_id)
    result = adapter.benchmark()
    return _models_envelope({"benchmark": result.model_dump(mode="json")})


# ---------------------------------------------------------------------------
# Work orders / Maintenance Center (advisory, read-only)
#
# Work orders are DERIVED from predictive-maintenance alerts and are fully
# traceable to the originating model + evidence (originating_model +
# source_recommendation_id + ranked_causes + evidence). Each proposed work order
# is created ``pending`` (operator approval required) and its creation is
# audited. Approval is a separate, audited operator action.
#
# A CMMS adapter provides a strictly READ-ONLY default (pull work orders + asset
# history). A write-back adapter -- which creates a CMMS *ticket* for an
# operator-approved work order -- is enabled only behind CMMS_WRITE_BACK_ENABLED.
# CRITICAL: a CMMS write-back is a business-system ticket, NEVER an OT/control
# path, and only ever happens after operator approval. The control boundary
# stays advisory / read-only on every work order.
# ---------------------------------------------------------------------------


def _persist_work_order(wo, *, audited: bool, actor: str = "system") -> None:
    """Persist a proposed work order (idempotent) and audit its creation once.

    Idempotent by the deterministic work-order id so repeated derivation does
    not duplicate a work order or reset an operator's decision.
    """
    if work_order_store.get(wo.work_order_id) is not None:
        return
    work_order_store.put(wo)
    if audited:
        store.audit(
            "workorder.created",
            payload={
                "work_order_id": wo.work_order_id,
                "asset_id": wo.asset_id,
                "originating_model": wo.originating_model,
                "source_recommendation_id": wo.source_recommendation_id,
                "source_alert_code": wo.source_alert_code,
            },
            actor=actor,
            subject=wo.work_order_id,
        )


def _route_pdm_recommendation_cards(fouling: float, actor: str = "system") -> None:
    """Ensure the PdM recommendation cards backing the work orders exist.

    A work order links back to its PdM recommendation card via
    ``source_recommendation_id``; routing the cards keeps that link resolvable.
    """
    cards = [pdm.build_pdm_card(rec) for rec in pdm.compute_recommendations(fouling)]
    _route_pdm_recommendations(cards, actor=actor)


@app.get("/api/v1/maintenance/work-orders")
def maintenance_work_orders(
    fouling: Optional[float] = None,
    user: Principal = Depends(get_current_user),
) -> dict:
    """Proposed work orders derived from predictive-maintenance alerts.

    Each work order is traceable to its originating model + evidence, created
    ``pending`` operator approval (audited on creation), and links back to its
    PdM recommendation card via ``source_recommendation_id``.
    """
    f = _wq_fouling(fouling)
    actor = _actor(user)
    _route_pdm_recommendation_cards(f, actor=actor)
    for wo in maintenance.propose_work_orders(f):
        _persist_work_order(wo, audited=True, actor=actor)
    return _pdm_envelope(
        {"work_orders": [w.model_dump(mode="json") for w in work_order_store.list()]}
    )


@app.get("/api/v1/maintenance/work-orders/{work_order_id}", dependencies=AUTHENTICATED)
def maintenance_work_order(work_order_id: str) -> dict:
    """Return a single work order (with full traceability + evidence)."""
    wo = work_order_store.get(work_order_id)
    if wo is None:
        raise HTTPException(status_code=404, detail=f"unknown work order: {work_order_id}")
    return _pdm_envelope({"work_order": wo.model_dump(mode="json")})


class WorkOrderDecisionRequest(BaseModel):
    status: str = Field(description="approved or rejected")
    actor: str = "operator"


@app.post("/api/v1/maintenance/work-orders/{work_order_id}/decision")
def decide_work_order(
    work_order_id: str,
    body: WorkOrderDecisionRequest,
    user: Principal = Depends(require_role("operator")),
) -> dict:
    """Record an operator approval decision on a work order (audited).

    This is an *operator approval* action only; it never writes to equipment.
    On approval, when CMMS write-back is enabled, an approved work order is
    written back as a CMMS *ticket* (a business-system record, never a control
    path). The decision and any ticket creation are audited.
    """
    decision = body.status.lower().strip()
    if decision not in _VALID_DECISIONS:
        raise HTTPException(
            status_code=422, detail=f"status must be one of {sorted(_VALID_DECISIONS)}"
        )
    wo = work_order_store.get(work_order_id)
    if wo is None:
        raise HTTPException(status_code=404, detail=f"unknown work order: {work_order_id}")

    actor = _actor(user, body.actor)
    wo.approval_status = ApprovalStatus(decision)
    wo.status = (
        WorkOrderStatus.approved if decision == "approved" else WorkOrderStatus.rejected
    )
    wo.approved_by = actor
    from canonical_water_model import now_iso as _now_iso

    wo.decided_at = _now_iso()
    store.audit(
        "workorder.decision",
        payload={"work_order_id": work_order_id, "status": decision},
        actor=actor,
        subject=work_order_id,
    )

    # Approved + write-back enabled -> create a CMMS ticket (never a control path).
    if decision == "approved":
        adapter = get_cmms_adapter()
        if adapter.write_enabled:
            try:
                ticket = adapter.create_work_order(wo, approved=True)
                wo = ticket
                store.audit(
                    "workorder.cmms.ticket_created",
                    payload={
                        "work_order_id": work_order_id,
                        "cmms_system": ticket.cmms_system,
                        "cmms_external_id": ticket.cmms_external_id,
                        "is_control_path": False,
                    },
                    actor=actor,
                    subject=work_order_id,
                )
            except cmms_pkg.CmmsWriteNotEnabled as exc:  # pragma: no cover - defensive
                raise HTTPException(status_code=409, detail=str(exc))

    work_order_store.put(wo)
    return _pdm_envelope({"work_order": wo.model_dump(mode="json")})


@app.get("/api/v1/maintenance/cmms/status", dependencies=AUTHENTICATED)
def maintenance_cmms_status() -> dict:
    """Describe the active CMMS adapter (read-only vs write-back)."""
    return _pdm_envelope(
        {"cmms": get_cmms_adapter().describe()}, DataProvenance.synthetic
    )


@app.get("/api/v1/maintenance/cmms/work-orders", dependencies=AUTHENTICATED)
def maintenance_cmms_work_orders() -> dict:
    """Pull the current work orders from the CMMS of record (read-only)."""
    adapter = get_cmms_adapter()
    orders = adapter.pull_work_orders()
    return _pdm_envelope(
        {
            "cmms": adapter.describe(),
            "work_orders": [w.model_dump(mode="json") for w in orders],
        },
        DataProvenance.synthetic,
    )


@app.get(
    "/api/v1/maintenance/cmms/asset-history/{asset_id}", dependencies=AUTHENTICATED
)
def maintenance_cmms_asset_history(asset_id: str) -> dict:
    """Pull an asset's historical maintenance records from the CMMS (read-only)."""
    adapter = get_cmms_adapter()
    history = adapter.pull_asset_history(asset_id)
    return _pdm_envelope(
        {
            "cmms": adapter.describe(),
            "asset_id": asset_id,
            "history": [h.model_dump(mode="json") for h in history],
        },
        DataProvenance.synthetic,
    )


# ---------------------------------------------------------------------------
# Condition Intelligence (advisory, read-only)
#
# A governed condition-model framework: each model publishes a full ModelSpec
# contract (equation source, feature spec, assumptions, valid range, version,
# uncertainty method, failure modes, explainability outputs). Per model the API
# exposes a back-test (precision / recall / false-alarm rate / lead time, with
# uncertainty), a confidence-calibration report and a distribution-drift check.
# Operators capture confirm/dismiss feedback on an alert; feedback is persisted
# by the durable store and routed through the existing audit trail. Every
# response carries the control boundary + provenance; nothing writes to control.
# ---------------------------------------------------------------------------


def _condition_envelope(
    payload: dict, provenance: DataProvenance = DataProvenance.preliminary
) -> dict:
    """Attach the read-only control boundary + provenance to a condition response."""
    return {
        **payload,
        "facility_id": wq.FACILITY_ID,
        "train_id": wq.TRAIN_ID,
        "provenance": provenance.value,
        "control_boundary": ControlBoundary().model_dump(),
    }


def _require_condition_model(model_id: str) -> None:
    if model_id not in condition.MODELS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown condition model: {model_id}; known: {condition.list_model_ids()}",
        )


class ConditionFeedbackRequest(BaseModel):
    decision: str = Field(description="confirm or dismiss")
    model_id: Optional[str] = None
    asset_id: Optional[str] = None
    recommendation_id: Optional[str] = None
    note: Optional[str] = None
    actor: str = "operator"


@app.get("/api/v1/condition/models", dependencies=AUTHENTICATED)
def condition_models() -> dict:
    """List every governed condition model with its full ModelSpec contract."""
    return _condition_envelope(
        {"models": [condition.model_spec_dict(mid) for mid in condition.list_model_ids()]}
    )


@app.get("/api/v1/condition/models/{model_id}/spec", dependencies=AUTHENTICATED)
def condition_model_spec(model_id: str) -> dict:
    """Return one model's published contract (equation source, valid range, ...)."""
    _require_condition_model(model_id)
    return _condition_envelope({"spec": condition.model_spec_dict(model_id)})


@app.get("/api/v1/condition/models/{model_id}/backtest", dependencies=AUTHENTICATED)
def condition_backtest(model_id: str) -> dict:
    """Back-test the model: precision / recall / false-alarm rate / lead time."""
    _require_condition_model(model_id)
    return _condition_envelope({"backtest": condition.backtest_dict(model_id)})


@app.get("/api/v1/condition/models/{model_id}/calibration", dependencies=AUTHENTICATED)
def condition_calibration(model_id: str, bins: int = 10) -> dict:
    """Confidence-calibration reliability report (ECE / MCE / Brier)."""
    _require_condition_model(model_id)
    return _condition_envelope(
        {"calibration": condition.calibration_dict(model_id, n_bins=max(1, bins))}
    )


@app.get("/api/v1/condition/models/{model_id}/drift", dependencies=AUTHENTICATED)
def condition_drift(model_id: str, shifted: bool = True) -> dict:
    """Drift check comparing a live window to the frozen baseline (drift flag)."""
    _require_condition_model(model_id)
    return _condition_envelope({"drift": condition.drift_dict(model_id, shifted=shifted)})


@app.post("/api/v1/condition/alerts/{alert_id}/feedback")
def condition_feedback(
    alert_id: str,
    body: ConditionFeedbackRequest,
    user: Principal = Depends(require_role("operator")),
) -> dict:
    """Capture an operator confirm/dismiss decision on a condition alert.

    Recording feedback is an operator/admin action (RBAC matrix) and never
    writes to equipment. The decision is persisted by the durable store and
    audited; it is the ground-truth signal the back-test/calibration harnesses
    consume.
    """
    try:
        record = store.record_feedback(
            alert_id,
            body.decision,
            recommendation_id=body.recommendation_id,
            asset_id=body.asset_id,
            model_id=body.model_id,
            actor=_actor(user, body.actor),
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    store.audit(
        "condition.feedback.recorded",
        payload={
            "feedback_id": record["feedback_id"],
            "alert_id": alert_id,
            "decision": record["decision"],
            "model_id": record["model_id"],
        },
        actor=record["actor"],
        subject=alert_id,
    )
    return _condition_envelope({"feedback": record})


@app.get("/api/v1/condition/feedback", dependencies=AUTHENTICATED)
def condition_feedback_list(alert_id: Optional[str] = None, limit: int = 100) -> dict:
    """List captured operator feedback (optionally filtered to one alert)."""
    if alert_id:
        feedback = store.feedback_for(alert_id)
    else:
        feedback = store.recent_feedback(limit)
    return _condition_envelope({"feedback": feedback})


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


def _value_envelope(
    payload: dict, provenance: DataProvenance, scope: Optional[Scope] = None
) -> dict:
    """Attach the read-only control boundary + provenance to a value response."""
    return {
        **payload,
        "tenant_id": scope.tenant_id if scope else config.DEFAULT_TENANT_ID,
        "facility_id": scope.facility_id if scope else wq.FACILITY_ID,
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
def energy_summary(
    fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Energy-by-asset + current-vs-optimal specific-energy summary (estimated)."""
    return _value_envelope(
        energy.energy_summary(_wq_fouling(fouling)), DataProvenance.estimated, scope
    )


@app.post("/api/v1/energy/optimize", dependencies=FEAT_ENERGY)
def energy_optimize(
    body: EnergyOptimizeRequest | None = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Optimal HP-pump setpoint + ESTIMATED savings (constrained RO optimisation)."""
    fouling = _wq_fouling(body.fouling if body else None)
    result = energy.optimization_result(fouling)
    return _value_envelope(
        {"optimization": result.model_dump(mode="json")}, DataProvenance.estimated, scope
    )


@app.get("/api/v1/energy/losses", dependencies=FEAT_ENERGY)
def energy_losses(
    fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Avoidable specific-energy losses (estimated, synthetic basis)."""
    losses = energy.losses(_wq_fouling(fouling))
    return _value_envelope(
        {"losses": [loss.model_dump(mode="json") for loss in losses]},
        DataProvenance.estimated,
        scope,
    )


@app.get("/api/v1/resilience/criticality", dependencies=FEAT_RESILIENCE)
def resilience_criticality(scope: Scope = Depends(facility_scope)) -> dict:
    """Resilience-criticality ranking of assets (highest impact/risk first)."""
    ranking = resil.criticality_ranking()
    return _value_envelope(
        {"criticality": [c.model_dump(mode="json") for c in ranking]},
        DataProvenance.preliminary,
        scope,
    )


@app.get("/api/v1/resilience/generator", dependencies=FEAT_RESILIENCE)
def resilience_generator(scope: Scope = Depends(facility_scope)) -> dict:
    """Preliminary standby-generator start probability + fuel endurance."""
    gen = resil.generator_status()
    return _value_envelope(
        {"generator": gen.model_dump(mode="json")}, DataProvenance.preliminary, scope
    )


def _route_resilience_recommendation(
    card, actor: str = "system", scope: Optional[Scope] = None
) -> None:
    """Route the grid-outage recommendation through the existing recommendation +
    audit path (pending, operator approval required, no control write). Idempotent
    by its deterministic id so repeated assessments do not duplicate the card or
    reset an operator's decision."""
    _apply_scope(card, scope)
    if reco_store.get(card.recommendation_id) is not None:
        return
    reco_store.put(card)
    store.save_recommendation(
        card.recommendation_id,
        card.model_dump(mode="json"),
        tenant_id=card.tenant_id,
        facility_id=card.facility_id,
        train_id=card.train_id,
        status=card.approval_status.value,
    )
    store.audit(
        "resilience.recommendation.created",
        payload={"recommendation_id": card.recommendation_id, "asset_id": card.asset_id},
        actor=actor,
        subject=card.recommendation_id,
        tenant_id=card.tenant_id,
        facility_id=card.facility_id,
    )


@app.post("/api/v1/resilience/grid-outage", dependencies=FEAT_RESILIENCE)
def resilience_grid_outage(
    body: GridOutageRequest | None = None,
    scope: Scope = Depends(facility_scope),
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
    _route_resilience_recommendation(card, actor=_actor(user), scope=scope)
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
        scope,
    )


@app.get("/api/v1/executive/value-summary", dependencies=FEAT_EXECUTIVE)
def executive_value_summary(
    fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Aggregated ESTIMATED value summary (illustrative, synthetic basis)."""
    summary = executive.value_summary(_wq_fouling(fouling))
    return _value_envelope(
        {"value_summary": summary.model_dump(mode="json"), "disclaimer": summary.disclaimer},
        DataProvenance.estimated,
        scope,
    )


@app.get("/api/v1/executive/roi", dependencies=FEAT_EXECUTIVE)
def executive_roi(
    fouling: Optional[float] = None, scope: Scope = Depends(facility_scope)
) -> dict:
    """Illustrative pilot ROI, annualized benefit + payback (ESTIMATED)."""
    estimate = executive.roi(_wq_fouling(fouling))
    return _value_envelope(
        {"roi": estimate.model_dump(mode="json"), "disclaimer": estimate.disclaimer},
        DataProvenance.estimated,
        scope,
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
        tenant_id=getattr(card, "tenant_id", None),
        facility_id=card.facility_id,
        train_id=card.train_id,
        status=card.approval_status.value,
    )
    store.audit(
        "assistant.recommendation.created",
        payload={"recommendation_id": card.recommendation_id, "asset_id": card.asset_id},
        subject=card.recommendation_id,
        tenant_id=getattr(card, "tenant_id", None),
        facility_id=card.facility_id,
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


# ---------------------------------------------------------------------------
# Operator Training Simulator (SIMULATION, sandboxed, read-only)
#
# A guided operator-training capability built on the platform's EXISTING
# replayable synthetic telemetry + scenario engines (synthetic PdM telemetry,
# the hydraulic what-if ``ScenarioType`` and the resilience grid-outage
# assessment). An operator injects a drill (pump degradation / leak / outage /
# storm-power-loss), diagnoses the SIMULATED twin snapshot, and has their
# actions + approvals captured in a sandbox and scored against an
# expected-response rubric to produce a durable training record.
#
# HARD BOUNDARY: this is a SIMULATION. The training sandbox CANNOT emit any
# command -- there is no control path, no OT connector, and no PLC/SCADA/VFD/
# valve/pump write. Every response carries the read-only control boundary,
# ``provenance = "simulated"`` and a mandatory SIMULATION disclaimer. Session
# lifecycle events are audited. Nothing here writes to any control system.
# ---------------------------------------------------------------------------


class TrainingSessionRequest(BaseModel):
    scenario_id: str
    operator: Optional[str] = None


class TrainingActionRequest(BaseModel):
    #: One of diagnosis | action | approval | note (sandboxed, never a command).
    kind: str = "action"
    text: str = Field(min_length=1, max_length=2000)
    rubric_key: Optional[str] = None
    approved: Optional[bool] = None


_TRAINING_ACTION_KINDS = {"diagnosis", "action", "approval", "note"}


def _training_envelope(payload: dict) -> dict:
    """Attach the read-only boundary + simulated provenance + disclaimer."""
    return {
        **payload,
        "facility_id": wq.FACILITY_ID,
        "train_id": wq.TRAIN_ID,
        "provenance": DataProvenance.simulated.value,
        "simulation": True,
        "disclaimer": training.TRAINING_DISCLAIMER,
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get("/api/v1/training/scenarios", dependencies=AUTHENTICATED)
def training_scenarios() -> dict:
    """List the reference operator-training drills (SIMULATION)."""
    return _training_envelope(
        {"scenarios": [s.model_dump(mode="json") for s in training.list_scenarios()]}
    )


@app.post("/api/v1/training/sessions")
def training_start_session(
    body: TrainingSessionRequest,
    user: Principal = Depends(get_current_user),
) -> dict:
    """Inject a drill scenario and open a sandboxed training session (SIMULATION).

    The injected twin snapshot reuses the platform's synthetic telemetry +
    read-only scenario engines; nothing is written to any control system.
    """
    operator = _actor(user, body.operator)
    try:
        session = training.inject_scenario(body.scenario_id, operator)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"unknown training scenario: {body.scenario_id}",
        )
    training_store.open_session(session)
    store.audit(
        "training.session.started",
        payload={
            "session_id": session.session_id,
            "scenario_id": session.scenario_id,
            "simulation": True,
        },
        actor=operator,
        subject=session.session_id,
    )
    return _training_envelope({"session": session.model_dump(mode="json")})


@app.get("/api/v1/training/sessions/{session_id}", dependencies=AUTHENTICATED)
def training_get_session(session_id: str) -> dict:
    """Return the current state of a training session (SIMULATION)."""
    session = training_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown training session: {session_id}")
    return _training_envelope({"session": session.model_dump(mode="json")})


@app.post("/api/v1/training/sessions/{session_id}/actions")
def training_capture_action(
    session_id: str,
    body: TrainingActionRequest,
    user: Principal = Depends(get_current_user),
) -> dict:
    """Capture an operator action/approval in the sandbox (SIMULATION, no command).

    The action is recorded for scoring only. The training sandbox has no
    control-write path: nothing here reaches any plant, OT, PLC or SCADA system.
    """
    kind = body.kind.lower().strip()
    if kind not in _TRAINING_ACTION_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"kind must be one of {sorted(_TRAINING_ACTION_KINDS)}",
        )
    action = training_store.capture_action(
        session_id,
        kind,
        body.text,
        rubric_key=body.rubric_key,
        approved=body.approved,
    )
    if action is None:
        raise HTTPException(status_code=404, detail=f"unknown training session: {session_id}")
    session = training_store.get_session(session_id)
    store.audit(
        "training.action.captured",
        payload={
            "session_id": session_id,
            "action_id": action.action_id,
            "kind": action.kind,
            "emitted_command": action.emitted_command,
        },
        actor=_actor(user),
        subject=session_id,
    )
    return _training_envelope(
        {
            "action": action.model_dump(mode="json"),
            "session": session.model_dump(mode="json"),
        }
    )


@app.post("/api/v1/training/sessions/{session_id}/submit")
def training_submit_session(
    session_id: str,
    user: Principal = Depends(get_current_user),
) -> dict:
    """Score the drill against its rubric and produce a training record (SIMULATION)."""
    record = training_store.score_session(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown training session: {session_id}")
    store.audit(
        "training.session.scored",
        payload={
            "session_id": session_id,
            "record_id": record.record_id,
            "scenario_id": record.scenario_id,
            "percentage": record.score.percentage,
            "passed": record.score.passed,
        },
        actor=_actor(user),
        subject=record.record_id,
    )
    return _training_envelope({"record": record.model_dump(mode="json")})


@app.get("/api/v1/training/records", dependencies=AUTHENTICATED)
def training_records() -> dict:
    """List the training records produced in this session store (SIMULATION)."""
    return _training_envelope(
        {"records": [r.model_dump(mode="json") for r in training_store.list_records()]}
    )


@app.post("/api/v1/reset")
def reset(user: Principal = Depends(require_role("engineer"))) -> dict:
    """Clear cached runs, recommendations, and audit trail (demo convenience).

    Resetting demo state is an engineer/admin action (RBAC matrix).
    """
    with _runs_lock:
        _runs.clear()
    with _latest_telemetry_lock:
        _latest_telemetry.clear()
        _gateway_state.clear()
    reco_store.clear()
    work_order_store.clear()
    training_store.reset()
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


# ---------------------------------------------------------------------------
# Model governance registry (D1/D2 governance) + regulatory compliance
# (advisory, read-only).
#
# ``GET .../models`` exposes the governance view of every deterministic
# analytical model (version, spec, current metrics, drift status vs a registered
# baseline). ``GET .../compliance/limits`` returns the operator-configured
# per-parameter regulatory limits from the A1 config store; ``.../compliance/
# status`` screens the current synthetic values against them (flagging
# exceedances); and ``POST .../reports/compliance`` renders a printable
# compliance summary. Everything here is advisory: the models are preliminary/
# synthetic (never validated) and nothing writes to any control system.
# ---------------------------------------------------------------------------


@app.get("/api/v1/models", dependencies=AUTHENTICATED)
def models_registry(fouling: Optional[float] = None) -> dict:
    """Model governance registry: versions, specs, current metrics, drift status."""
    registry = model_registry.build_registry(_wq_fouling(fouling))
    return {
        "models": [entry.model_dump(mode="json") for entry in registry],
        "count": len(registry),
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get("/api/v1/models/{model_id}", dependencies=AUTHENTICATED)
def model_detail(model_id: str, fouling: Optional[float] = None) -> dict:
    """Governance detail for a single registered model."""
    entry = model_registry.get_model(model_id, _wq_fouling(fouling))
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown model: {model_id}; known: {model_registry.list_model_ids()}",
        )
    return {
        **entry.model_dump(mode="json"),
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get("/api/v1/compliance/limits", dependencies=AUTHENTICATED)
def compliance_limits() -> dict:
    """Return the configured per-parameter regulatory limits (A1 config store)."""
    limits = config_store.limits()
    return {
        "limits": [limit.model_dump(mode="json") for limit in limits],
        "count": len(limits),
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.get("/api/v1/compliance/status", dependencies=AUTHENTICATED)
def compliance_status(fouling: Optional[float] = None) -> dict:
    """Screen current values against the configured limits (flag exceedances)."""
    evaluation = compliance.evaluate(config_store.limits(), _wq_fouling(fouling))
    return {
        **evaluation.model_dump(mode="json"),
        "control_boundary": ControlBoundary().model_dump(),
    }


@app.post("/api/v1/reports/compliance")
def compliance_report(
    fouling: Optional[float] = None,
    user: Principal = Depends(get_current_user),
) -> PlainTextResponse:
    """Generate a downloadable Markdown regulatory-compliance summary.

    Screens current synthetic values against the configured regulatory limits,
    flags every exceedance with its regulatory basis (provenance), and ends with
    the mandatory read-only control-boundary footer + standard disclaimer.
    """
    limits = config_store.limits()
    evaluation = compliance.evaluate(limits, _wq_fouling(fouling))
    document = build_compliance_report(evaluation, limits)
    store.audit(
        "report.compliance.generated",
        payload={
            "exceedances": len(evaluation.exceedances),
            "compliant": evaluation.compliant,
        },
        actor=_actor(user),
        subject=evaluation.facility_id,
    )
    filename = f"compliance-report-{evaluation.facility_id}.md"
    return PlainTextResponse(
        content=document,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
