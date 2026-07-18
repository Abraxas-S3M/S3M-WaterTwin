"""FastAPI surface for watertwin-ingest (thin wrapper over :class:`IngestService`).

Endpoints are deliberately minimal and every mutating/reading path is tenant-
scoped. Authentication in production is the platform's Keycloak JWT (the tenant
claim drives isolation); here the tenant is taken from the ``X-Tenant-Id`` header
so the service is runnable and testable without a live identity provider. The
service is advisory and read-only to OT — there is no control endpoint.
"""watertwin-ingest FastAPI service.

Exposes the human-in-the-loop ingest flow for customer engineering files:

    POST /api/v1/ingest/uploads                 store an uploaded file
    POST /api/v1/ingest/uploads/{id}/classify   confirm/correct class + scope
    POST /api/v1/ingest/uploads/{id}/parse      enqueue a sandboxed parse
    GET  /api/v1/ingest/uploads/{id}/result     the ParseResult
    GET  /api/v1/ingest/uploads/{id}/proposal   the ChangeProposal

Classification MUST be confirmed by a human before a file is parsed — the
sniffed guess is only a hint. Every response carries the read-only
:class:`ControlBoundary`; nothing here writes to the canonical model or to OT.
"""watertwin-ingest: immutable customer-file intake service.

An OPTIONAL, independently deployable FastAPI service that receives customer
files, stores them immutably (content-addressed, write-once), scans them
structurally, and tracks them through a status lifecycle. NO parsing happens
here.

Architectural boundaries (the point of this service):

* It has **no direct database connection** to the canonical store. Every
  auditable action is posted to watertwin-api over the same authenticated HTTP
  API a human uses (:mod:`app.audit_client`).
* It has **no OT network access** -- it cannot reach MQTT, OPC UA, Modbus, or
  the edge gateway (enforced by ``tests/test_ot_write_forbid.py``).
* It is **optional**: with it stopped, the rest of the platform still works.
* Under a one-way / data-diode ``DEPLOYMENT_PROFILE`` it is disabled: it starts
  and serves ``/health`` but returns 503 on every ingest route.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request, Response, status

from . import config, deployment
from .control_boundary import CONTROL_BOUNDARY, safety_invariant_intact
from .deployment import IngestionDisabled
from .quotas import QuotaExceeded
from .residency import ResidencyViolation
from .scanning import MalwareDetected
from .service import IngestService
from .tenancy import CrossTenantAccessDenied, UploadNotFound
from contextlib import asynccontextmanager
from typing import Any

from canonical_water_model import ControlBoundary
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .models import ClassifyRequest, UploadStateResponse, UploadStatus
from .parsers import (
    ParseScope,
    ParseStatus,
    UnknownFormatError,
    UnsafeContentError,
    guard_unsafe_content,
    sniff_format,
    supported_formats,
)
from .proposal import ChangeProposal, build_proposal
from .reconciler import (
    CanonicalConfigClient,
    CanonicalConfigError,
    reconcile,
)
from .store import UploadRecord, UploadStore


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield
    store: UploadStore | None = getattr(app.state, "upload_store", None)
    if store is not None:
        store.shutdown()
import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from canonical_water_model import ControlBoundary

from watertwin_observability import configure_logging

from . import auth, config, events, lifecycle, scanner, storage
from .audit_client import AuditClient, AuditError, build_audit_client
from .auth import Principal
from .models import IngestStatus, UploadRecord
from .storage import OversizeError, StoredObject

logger = logging.getLogger("watertwin.ingest")

configure_logging(config.SERVICE_NAME)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# --------------------------------------------------------------------------- #
# Process state (in-memory record index + injectable collaborators). The record
# index tracks intake metadata only; file bytes live in the write-once store and
# the durable canonical state lives in watertwin-api (reached over HTTP).
# --------------------------------------------------------------------------- #

_LOCK = threading.RLock()
_RECORDS: dict[str, UploadRecord] = {}
_STORED: dict[str, StoredObject] = {}
_DELETED: set[str] = set()

_audit: AuditClient = build_audit_client()
_backend: storage.StorageBackend = storage.build_backend()
_antivirus: scanner.AntivirusScanner = scanner.build_antivirus()


class RateLimiter:
    """A simple per-tenant fixed-window rate limiter (in-memory)."""

    def __init__(self, max_events: int, window_s: float) -> None:
        self.max_events = max_events
        self.window_s = window_s
        self._windows: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            start, count = self._windows.get(key, (now, 0))
            if now - start >= self.window_s:
                start, count = now, 0
            if count >= self.max_events:
                self._windows[key] = (start, count)
                return False
            self._windows[key] = (start, count + 1)
            return True

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()


_rate_limiter = RateLimiter(config.RATE_LIMIT_MAX_UPLOADS, config.RATE_LIMIT_WINDOW_S)


def get_audit_client() -> AuditClient:
    return _audit


def set_audit_client(client: AuditClient) -> None:
    """Inject an audit client (used by tests)."""
    global _audit
    _audit = client


def get_backend() -> storage.StorageBackend:
    return _backend


def get_antivirus() -> scanner.AntivirusScanner:
    return _antivirus


def set_antivirus(av: scanner.AntivirusScanner) -> None:
    """Inject an antivirus backend (used by tests)."""
    global _antivirus
    _antivirus = av


def reset_state() -> None:
    """Clear all in-memory intake state (used by tests)."""
    with _LOCK:
        _RECORDS.clear()
        _STORED.clear()
        _DELETED.clear()
    _rate_limiter.reset()


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    auth.log_auth_mode()
    if config.inbound_file_transfer_forbidden():
        logger.warning(
            "DEPLOYMENT_PROFILE=%s: inbound file transfer is DISABLED. The service "
            "serves /health but returns 503 on every ingest route.",
            config.deployment_profile(),
        )
    else:
        logger.info("DEPLOYMENT_PROFILE=%s: inbound file transfer enabled.", config.deployment_profile())
    events.get_bus()
    yield


app = FastAPI(
    title="S3M-WaterTwin Ingest",
    version=config.SERVICE_VERSION,
    description="Hardened, tenant-isolated, advisory file ingestion (read-only to OT).",
)

_service = IngestService()


def _require_tenant(x_tenant_id: str | None) -> str:
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing X-Tenant-Id (tenant scope)",
        )
    return x_tenant_id


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness + the fixed advisory/read-only posture."""
    return {
        "service": config.SERVICE_NAME,
        "version": config.SERVICE_VERSION,
        "status": "ok",
        "deployment_profile": deployment.get_profile(),
        "ingestion_enabled": deployment.ingestion_enabled(),
        "safety_invariant_intact": safety_invariant_intact(),
        **CONTROL_BOUNDARY.as_dict(),
    }


@app.get("/capabilities")
def capabilities() -> dict[str, object]:
    """What the dashboard should render (nav gating) + safety posture."""
    return _service.capabilities()


@app.post("/api/v1/ingest/uploads", status_code=status.HTTP_201_CREATED)
async def upload(
    request: Request,
    parser: str,
    filename: str = "upload.bin",
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_actor: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    """Accept a raw file body (``application/octet-stream``) and run the pipeline.

    The body is the file bytes; ``parser`` and ``filename`` are query params. Raw
    body (rather than multipart) keeps the dependency surface minimal.
    """
    tenant = _require_tenant(x_tenant_id)
    data = await request.body()
    try:
        record = _service.upload(
            tenant_id=tenant,
            uploaded_by=x_actor or "unknown",
            filename=filename,
            data=data,
            parser=parser,
        )
    except IngestionDisabled as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except QuotaExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=exc.as_dict()
        ) from exc
    except MalwareDetected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ResidencyViolation as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return record.metadata()


@app.get("/api/v1/ingest/uploads")
def list_uploads(
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    tenant = _require_tenant(x_tenant_id)
    return {
        "uploads": _service.list_uploads(caller_tenant=tenant),
        "control_boundary": CONTROL_BOUNDARY.as_dict(),
    }


@app.get("/api/v1/ingest/uploads/{upload_id}")
def get_upload(
    upload_id: str,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    tenant = _require_tenant(x_tenant_id)
    try:
        return _service.get_metadata(caller_tenant=tenant, upload_id=upload_id)
    except CrossTenantAccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except UploadNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@app.get("/api/v1/ingest/uploads/{upload_id}/content")
def get_upload_content(
    upload_id: str,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> Response:
    tenant = _require_tenant(x_tenant_id)
    try:
        content = _service.get_content(caller_tenant=tenant, upload_id=upload_id)
    except CrossTenantAccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except UploadNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(content=content, media_type="application/octet-stream")


@app.get("/api/v1/ingest/uploads/{upload_id}/audit")
def get_upload_audit(
    upload_id: str,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    tenant = _require_tenant(x_tenant_id)
    return {
        "upload_id": upload_id,
        "events": _service.audit_trail(caller_tenant=tenant, upload_id=upload_id),
        "chain_ok": _service.verify_audit()["ok"],
    }
    description=(
        "Sandboxed customer-file ingestion: parse an EPANET .inp, reconcile it "
        "against the canonical configuration, and propose changes for human "
        "review. Read-only to the canonical model and to OT."
    ),
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.upload_store = UploadStore(
    scratch_dir=config.SCRATCH_DIR,
    timeout_s=config.PARSE_TIMEOUT_S,
    memory_mb=config.MEMORY_CAP_MB,
    max_fsize_bytes=config.MAX_SCRATCH_BYTES,
    allow_root=config.ALLOW_ROOT_WORKER,
)
app.state.canonical_client = None


def get_store() -> UploadStore:
    return app.state.upload_store


def get_canonical_client() -> CanonicalConfigClient:
    """Return the injected canonical client (tests) or the config-resolved one."""
    client = getattr(app.state, "canonical_client", None)
    if client is None:
        client = CanonicalConfigClient(
            base_url=config.WATERTWIN_API_URL, token=config.WATERTWIN_API_TOKEN
        )
        app.state.canonical_client = client
    return client


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "control_boundary": ControlBoundary().model_dump()}


def _state(record: UploadRecord, message: str | None = None) -> UploadStateResponse:
    return UploadStateResponse(
        upload_id=record.upload_id,
        filename=record.filename,
        size_bytes=record.size_bytes,
        status=record.status,
        classified=record.classified,
        sniffed_format=record.sniffed_format,
        confirmed_format=record.scope.file_format if record.scope else None,
        scope_sections=record.scope.sections if record.scope else [],
        supported_formats=supported_formats(),
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
        message=message,
    )


def _require(store: UploadStore, upload_id: str) -> UploadRecord:
    record = store.get(upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown upload '{upload_id}'")
    return record


@app.get("/health")
def health() -> dict[str, Any]:
    return _envelope(
        {
            "service": config.SERVICE_NAME,
            "version": config.SERVICE_VERSION,
            "status": "ok",
            "supported_formats": supported_formats(),
        }
    )


@app.post("/api/v1/ingest/uploads", status_code=201)
async def create_upload(
    file: UploadFile = File(...),
    store: UploadStore = Depends(get_store),
) -> dict[str, Any]:
    """Store an uploaded file and return its state (awaiting human classification).

    The file is refused if it is too large or carries an XML external-entity /
    DTD attack. A best-effort format guess is returned as a hint only — a human
    must confirm it via the ``classify`` endpoint before any parse runs.
    """
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds the {config.MAX_UPLOAD_BYTES}-byte limit",
        )
    if not content:
        raise HTTPException(status_code=422, detail="empty upload")
    try:
        guard_unsafe_content(content)
    except UnsafeContentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record = store.create(file.filename or "upload.inp", content, sniff_format(content))
    return _envelope(
        _state(
            record,
            message="stored; confirm the classification via /classify before parsing",
        ).model_dump(mode="json")
    )


@app.post("/api/v1/ingest/uploads/{upload_id}/classify")
def classify_upload(
    upload_id: str,
    body: ClassifyRequest,
    store: UploadStore = Depends(get_store),
) -> dict[str, Any]:
    """Confirm/correct the file's classification and extraction scope (human step)."""
    record = _require(store, upload_id)
    if body.file_format not in supported_formats():
        raise HTTPException(
            status_code=422,
            detail=(
                f"unsupported file_format '{body.file_format}'; "
                f"supported: {supported_formats()}"
            ),
        )
    scope = ParseScope(file_format=body.file_format, sections=body.sections, note=body.note)
    store.classify(record, scope)
    return _envelope(
        _state(record, message="classification confirmed; you may now enqueue a parse").model_dump(
            mode="json"
        )
    )


@app.post("/api/v1/ingest/uploads/{upload_id}/parse", status_code=202)
def parse_upload(
    upload_id: str,
    store: UploadStore = Depends(get_store),
) -> dict[str, Any]:
    """Enqueue a sandboxed parse. Requires a human-confirmed classification."""
    record = _require(store, upload_id)
    if not record.classified or record.scope is None:
        raise HTTPException(
            status_code=409,
            detail="classification must be confirmed by a human before parsing",
        )
    store.enqueue_parse(record)
    return _envelope(_state(record, message="parse enqueued").model_dump(mode="json"))


@app.get("/api/v1/ingest/uploads/{upload_id}/result")
def get_result(
    upload_id: str,
    store: UploadStore = Depends(get_store),
) -> dict[str, Any]:
    """Return the current ParseResult (or the in-progress status)."""
    record = _require(store, upload_id)
    if record.parse_result is None:
        return _envelope(
            {
                "upload_id": upload_id,
                "status": record.status.value,
                "result": None,
                "message": "no parse result yet",
            }
        )
    return _envelope(
        {
            "upload_id": upload_id,
            "status": record.status.value,
            "result": record.parse_result.model_dump(mode="json"),
        }
    )


@app.get("/api/v1/ingest/uploads/{upload_id}/proposal")
def get_proposal(
    upload_id: str,
    store: UploadStore = Depends(get_store),
    client: CanonicalConfigClient = Depends(get_canonical_client),
) -> dict[str, Any]:
    """Return the ChangeProposal, reconciling against the canonical config on demand."""
    record = _require(store, upload_id)
    proposal = _ensure_proposal(record, client)
    return _envelope({"upload_id": upload_id, "proposal": proposal.model_dump(mode="json")})


def _ensure_proposal(
    record: UploadRecord, client: CanonicalConfigClient
) -> ChangeProposal:
    with record.lock:
        if record.proposal is not None:
            return record.proposal
        result = record.parse_result
        status = record.status
    if result is None or status in {UploadStatus.received, UploadStatus.classified,
                                    UploadStatus.queued, UploadStatus.parsing}:
        raise HTTPException(status_code=409, detail="parse not complete for this upload")
    if result.status is ParseStatus.parse_failed:
        raise HTTPException(
            status_code=409, detail=f"cannot build a proposal from a failed parse: {result.error}"
        )
    try:
        canonical_records = client.fetch_records()
    except CanonicalConfigError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    reconcile_result = reconcile(
        result, canonical_records, match_threshold=config.MATCH_THRESHOLD
    )
    proposal = build_proposal(
        reconcile_result, result, source_file=record.filename, upload_id=record.upload_id
    )
    with record.lock:
        record.reconcile_result = reconcile_result
        record.proposal = proposal
    return proposal


# Surface a clean 422 for an unknown format requested through any path.
@app.exception_handler(UnknownFormatError)
async def _unknown_format_handler(_request: Any, exc: UnknownFormatError) -> Any:
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=422, content={"detail": str(exc)})
    description="Immutable customer-file intake (receive, store, scan, track). No parsing.",
    lifespan=_lifespan,
)


# --------------------------------------------------------------------------- #
# Guards / dependencies
# --------------------------------------------------------------------------- #


def profile_guard() -> None:
    """Return 503 on every ingest route under a one-way / data-diode profile.

    Runs before authentication so the disabled state is reported uniformly (the
    service is up; inbound file transfer is simply not accepted here).
    """
    if config.inbound_file_transfer_forbidden():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=config.inbound_forbidden_reason(),
        )


def _record_visible_to(record: UploadRecord, user: Principal) -> bool:
    return user.can_access_tenant(record.tenant_id) and str(record.ingest_id) not in _DELETED


def _get_visible_record(ingest_id: str, user: Principal) -> UploadRecord:
    with _LOCK:
        record = _RECORDS.get(ingest_id)
        if record is None or not _record_visible_to(record, user):
            # A cross-tenant / deleted / unknown id is indistinguishable: 404.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
        return record


# --------------------------------------------------------------------------- #
# Health / readiness (open; no auth, no profile guard)
# --------------------------------------------------------------------------- #


@app.get("/health")
def health() -> dict:
    cb = ControlBoundary()
    return {
        "service": config.SERVICE_NAME,
        "version": config.SERVICE_VERSION,
        "status": "healthy",
        "deployment_profile": config.deployment_profile(),
        "inbound_file_transfer_enabled": not config.inbound_file_transfer_forbidden(),
        "storage_backend": get_backend().name,
        "antivirus": get_antivirus().name,
        "event_bus": events.get_bus().status(),
        "control_mode": cb.control_mode,
        "operator_approval_required": cb.operator_approval_required,
        "control_write_enabled": cb.control_write_enabled,
        "control_boundary": cb.model_dump(),
    }


@app.get("/ready")
def ready() -> dict:
    return {
        "service": config.SERVICE_NAME,
        "ready": True,
        "inbound_file_transfer_enabled": not config.inbound_file_transfer_forbidden(),
    }


# --------------------------------------------------------------------------- #
# Ingest routes (all gated by the profile guard; RBAC per route)
# --------------------------------------------------------------------------- #


@app.post("/api/v1/ingest/uploads", dependencies=[Depends(profile_guard)])
async def create_upload(
    file: UploadFile = File(...),
    facility_id: str = Form(...),
    declared_class: str = Form("generic"),
    user: Principal = Depends(auth.require_upload),
) -> UploadRecord:
    """Receive a file: stream to the write-once store, scan, and track it.

    ``tenant_id`` is bound from the caller's token, never the request body.
    """
    tenant_id = user.tenant_id
    if not _rate_limiter.allow(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="per-tenant upload rate limit exceeded; retry later",
        )

    declared_class = (declared_class or "generic").strip() or "generic"
    filename = file.filename or "upload.bin"
    content_type_declared = file.content_type or "application/octet-stream"
    size_cap = scanner.size_cap_for(declared_class)

    # Stream to staging, hashing + size-capping as we go. Oversize is rejected
    # PRE-STORAGE (nothing is committed and no record is created).
    writer = get_backend().new_writer(size_cap)
    try:
        while True:
            chunk = await file.read(config.STREAM_CHUNK_BYTES)
            if not chunk:
                break
            writer.write(chunk)
    except OversizeError as exc:
        logger.info("rejected oversize upload %r (tenant=%s): %s", filename, tenant_id, exc)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    finally:
        await file.close()

    staged = writer.finish()
    audit = get_audit_client()

    record = UploadRecord(
        tenant_id=tenant_id,
        facility_id=facility_id,
        filename=filename,
        content_type_declared=content_type_declared,
        content_type_detected=content_type_declared,
        size_bytes=staged.size_bytes,
        sha256=staged.sha256,
        uploaded_by=user.actor,
        uploaded_at=_now_iso(),
        status=IngestStatus.received,
        scope=f"{tenant_id}/{facility_id}",
    )
    ingest_id = str(record.ingest_id)

    try:
        lifecycle.record_initial(record, actor=user.actor, audit=audit)
        with _LOCK:
            _RECORDS[ingest_id] = record
        events.publish_ingest_received(
            ingest_id=ingest_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            sha256=staged.sha256,
            size_bytes=staged.size_bytes,
        )
        lifecycle.transition(record, IngestStatus.scanning, actor=user.actor, audit=audit)

        try:
            outcome = scanner.scan(
                staged,
                filename=filename,
                declared_class=declared_class,
                antivirus=get_antivirus(),
            )
        except scanner.ScanRejected as exc:
            record.content_type_detected = scanner.sniff(staged.header)[0]
            lifecycle.transition(
                record,
                IngestStatus.scan_failed,
                actor=user.actor,
                audit=audit,
                error=f"{exc.code}: {exc.reason}",
            )
            staged.discard()
            events.publish_ingest_failed(
                ingest_id=ingest_id,
                tenant_id=tenant_id,
                facility_id=facility_id,
                code=exc.code,
                reason=exc.reason,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": exc.code, "reason": exc.reason, "ingest_id": ingest_id},
            ) from exc

        record.content_type_detected = outcome.content_type_detected
        record.detected_class = outcome.detected_class
        stored = get_backend().commit(staged, tenant_id)
        with _LOCK:
            _STORED[ingest_id] = stored
        lifecycle.transition(record, IngestStatus.classified, actor=user.actor, audit=audit)
        events.publish_ingest_scanned(
            ingest_id=ingest_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            detected_class=outcome.detected_class,
            content_type=outcome.content_type_detected,
        )
    except AuditError as exc:  # fail-safe: audit must be recorded
        staged.discard()
        logger.error("audit unavailable during intake of %r: %s", filename, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit trail unavailable; intake refused (fail-safe)",
        ) from exc

    return record


@app.get("/api/v1/ingest/uploads", dependencies=[Depends(profile_guard)])
def list_uploads(
    user: Principal = Depends(auth.require_ingest_access),
    limit: int = Query(config.DEFAULT_PAGE_SIZE, ge=1, le=config.MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict:
    """List uploads for the caller's tenant (paginated, tenant-scoped)."""
    with _LOCK:
        visible = [
            r
            for r in _RECORDS.values()
            if _record_visible_to(r, user)
        ]
    visible.sort(key=lambda r: r.uploaded_at, reverse=True)
    total = len(visible)
    page = visible[offset : offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [r.model_dump(mode="json") for r in page],
    }


@app.get("/api/v1/ingest/uploads/{ingest_id}", dependencies=[Depends(profile_guard)])
def get_upload(
    ingest_id: str,
    user: Principal = Depends(auth.require_ingest_access),
) -> UploadRecord:
    """Return a single upload record (tenant-scoped; 404 if not visible)."""
    return _get_visible_record(ingest_id, user)


@app.get("/api/v1/ingest/uploads/{ingest_id}/content", dependencies=[Depends(profile_guard)])
def get_upload_content(
    ingest_id: str,
    user: Principal = Depends(auth.require_admin),
) -> StreamingResponse:
    """Stream the immutable stored bytes back (admin only)."""
    record = _get_visible_record(ingest_id, user)
    with _LOCK:
        stored = _STORED.get(ingest_id)
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no stored content for this upload"
        )
    fh = get_backend().open(stored.key)
    return StreamingResponse(
        storage.iter_file(fh, config.STREAM_CHUNK_BYTES),
        media_type=record.content_type_detected or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{record.filename}"'},
    )


@app.delete("/api/v1/ingest/uploads/{ingest_id}", dependencies=[Depends(profile_guard)])
def delete_upload(
    ingest_id: str,
    user: Principal = Depends(auth.require_upload),
) -> dict:
    """Soft-delete an upload. The record is hidden but the audit trail is retained."""
    record = _get_visible_record(ingest_id, user)
    with _LOCK:
        _DELETED.add(ingest_id)
    try:
        get_audit_client().record(
            kind="ingest.deleted",
            actor=user.actor,
            subject=ingest_id,
            payload={
                "tenant_id": record.tenant_id,
                "facility_id": record.facility_id,
                "filename": record.filename,
                "sha256": record.sha256,
                "soft_delete": True,
            },
        )
    except AuditError as exc:  # keep the delete, surface the audit failure
        logger.error("audit unavailable during soft-delete of %s: %s", ingest_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit trail unavailable; delete not confirmed (fail-safe)",
        ) from exc
    return {"ingest_id": ingest_id, "status": "deleted", "audit_retained": True}
