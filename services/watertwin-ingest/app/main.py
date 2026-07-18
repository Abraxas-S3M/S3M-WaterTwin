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
"""

from __future__ import annotations

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


app = FastAPI(
    title="S3M-WaterTwin Ingest",
    version=config.SERVICE_VERSION,
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
