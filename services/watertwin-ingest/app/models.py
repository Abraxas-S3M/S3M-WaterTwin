"""API request/response schemas for the ingest service.

These are transport models only. The domain models live in ``app.parsers``
(:class:`ParseResult`), ``app.reconciler`` and ``app.proposal``.
"""Pydantic models for watertwin-ingest.

An :class:`UploadRecord` tracks a single received file through its status
lifecycle (:class:`IngestStatus`). No parsing happens in this service; the
record captures intake metadata, the immutable content address (``sha256`` +
size), and an append-only :attr:`UploadRecord.status_history` of every
transition (recorded by :mod:`app.lifecycle`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class UploadStatus(str, Enum):
    """Lifecycle of an uploaded file inside the ingest service.

    ``received`` — stored, awaiting human classification. ``classified`` — a
    human confirmed the format/scope. ``queued``/``parsing`` — a parse is
    enqueued/running in the sandbox. ``parsed``/``partial`` — a ParseResult is
    available (``partial`` when some content was routed to ``unparsed``).
    ``parse_failed`` — the worker crashed/timed out or the input was rejected.
    ``rejected`` — the upload was refused before parsing (e.g. an XXE attempt).
    """

    received = "received"
    classified = "classified"
    queued = "queued"
    parsing = "parsing"
    parsed = "parsed"
    partial = "partial"
    parse_failed = "parse_failed"
    rejected = "rejected"


class ClassifyRequest(BaseModel):
    """A human's confirmation/correction of an upload's classification.

    Classification of a critical-infrastructure file is never accepted from the
    content sniffer alone — a human must confirm the ``file_format`` (and,
    optionally, restrict the ``sections`` to extract) via this request.
    """

    file_format: str = Field(min_length=1)
    sections: list[str] = Field(default_factory=list)
    note: str | None = None


class UploadStateResponse(BaseModel):
    """The current state of an upload."""

    upload_id: str
    filename: str
    size_bytes: int
    status: UploadStatus
    classified: bool
    sniffed_format: str | None = None
    confirmed_format: str | None = None
    scope_sections: list[str] = Field(default_factory=list)
    supported_formats: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: str
    updated_at: str
    message: str | None = None
def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class IngestStatus(str, Enum):
    """The status lifecycle of a received file.

    Only :mod:`app.lifecycle` moves a record between these states, and only
    along the explicit allowed-transition map defined there.
    """

    received = "received"
    scanning = "scanning"
    scan_failed = "scan_failed"
    classified = "classified"
    parsing = "parsing"
    parse_failed = "parse_failed"
    parsed = "parsed"
    proposed = "proposed"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"


class StatusTransition(BaseModel):
    """A single append-only entry in an :class:`UploadRecord` status history."""

    status: IngestStatus
    at: str = Field(default_factory=_now_iso)
    actor: str
    note: str | None = None


class UploadRecord(BaseModel):
    """Intake metadata + lifecycle state for one received file.

    Every field is required except ``error``, ``scope`` and ``detected_class``
    (which are populated as the file moves through the lifecycle). ``tenant_id``
    is always bound from the caller's token at intake, never from the request
    body.
    """

    ingest_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: str
    facility_id: str
    filename: str
    content_type_declared: str
    content_type_detected: str
    size_bytes: int
    sha256: str
    uploaded_by: str
    uploaded_at: str
    status: IngestStatus
    detected_class: str | None = None
    scope: str | None = None
    error: str | None = None
    status_history: list[StatusTransition] = Field(default_factory=list)
