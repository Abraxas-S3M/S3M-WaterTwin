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
