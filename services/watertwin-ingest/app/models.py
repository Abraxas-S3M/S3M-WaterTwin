"""API request/response schemas for the ingest service.

These are transport models only. The domain models live in ``app.parsers``
(:class:`ParseResult`), ``app.reconciler`` and ``app.proposal``.
"""

from __future__ import annotations

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
