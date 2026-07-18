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
