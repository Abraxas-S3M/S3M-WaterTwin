"""FastAPI surface for watertwin-ingest (thin wrapper over :class:`IngestService`).

Endpoints are deliberately minimal and every mutating/reading path is tenant-
scoped. Authentication in production is the platform's Keycloak JWT (the tenant
claim drives isolation); here the tenant is taken from the ``X-Tenant-Id`` header
so the service is runnable and testable without a live identity provider. The
service is advisory and read-only to OT — there is no control endpoint.
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
