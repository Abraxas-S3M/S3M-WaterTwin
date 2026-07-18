"""Pydantic DTOs for the watertwin-ingest API.

These mirror the TypeScript ingest types consumed by the dashboard
(``apps/dashboard/src/api/types.ts``). Everything here is declarative data;
nothing describes or triggers a control action.
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

from typing import Literal

from pydantic import BaseModel, Field

IngestClass = Literal["epanet_inp", "unknown"]
IngestPanel = Literal[
    "asset-hierarchy",
    "tag-mapping",
    "alarm-thresholds",
    "rated-equipment",
    "process-stages",
    "lab-methods",
    "user-roles",
]
IngestUploadStatus = Literal[
    "classified", "previewed", "submitted", "approved", "rejected"
]
IngestChangeType = Literal["new", "update", "conflict"]
DataProvenance = Literal["synthetic", "simulated", "preliminary", "estimated", "measured"]


class ControlBoundaryModel(BaseModel):
    """The advisory/read-only control boundary echoed on every response."""

    control_mode: str = "advisory"
    operator_approval_required: bool = True
    control_write_enabled: bool = False


class IngestAcceptedType(BaseModel):
    extension: str
    label: str
    max_bytes: int


class IngestStatusResponse(BaseModel):
    available: bool
    enabled: bool
    deployment_profile: str
    accepted_types: list[IngestAcceptedType]
    control_boundary: ControlBoundaryModel = Field(default_factory=ControlBoundaryModel)


class IngestScope(BaseModel):
    facility_id: str | None = None
    entity: str | None = None


class IngestClassifyRequest(BaseModel):
    filename: str
    size_bytes: int
    content: str
    confirmed_class: IngestClass | None = None
    scope: IngestScope | None = None


class IngestClassification(BaseModel):
    upload_id: str
    filename: str
    sha256: str
    size_bytes: int
    suggested_class: IngestClass
    confidence: float
    detail: str
    supported_classes: list[IngestClass]


class IngestEntityCount(BaseModel):
    entity: str
    label: str
    found: int
    matched: int
    added: int
    conflicts: int


class IngestUnparsedRow(BaseModel):
    line: int
    section: str
    raw: str
    reason: str


class IngestDiffRow(BaseModel):
    row_id: str
    entity: str
    config_id: str
    field: str
    current_value: str | None = None
    proposed_value: str
    source_ref: str
    provenance: DataProvenance
    change_type: IngestChangeType
    match_confidence: float
    safety_relevant: bool


class IngestDiffGroup(BaseModel):
    panel: IngestPanel
    label: str
    rows: list[IngestDiffRow]


class IngestPreview(BaseModel):
    upload_id: str
    status: Literal["pending", "ready", "error"]
    suggested_class: IngestClass
    entity_counts: list[IngestEntityCount]
    unparsed: list[IngestUnparsedRow]
    diff: list[IngestDiffGroup]


class IngestRowDecision(BaseModel):
    row_id: str
    accepted: bool
    reject_reason: str | None = None


class IngestSubmitRequest(BaseModel):
    upload_id: str
    actor: str
    decisions: list[IngestRowDecision]


class IngestCreatedVersion(BaseModel):
    entity: str
    config_id: str
    version: int
    version_id: str
    status: str


class IngestSubmitResult(BaseModel):
    upload_id: str
    created_versions: list[IngestCreatedVersion]
    accepted_count: int
    rejected_count: int
    requires_separate_approver: bool
    self_approval_blocked: bool
    blocked_entities: list[str]
    message: str
    control_boundary: ControlBoundaryModel = Field(default_factory=ControlBoundaryModel)


class IngestHistoryItem(BaseModel):
    upload_id: str
    filename: str
    sha256: str
    uploader: str
    timestamp: str
    upload_class: IngestClass
    status: IngestUploadStatus
    config_version: int | None = None
    approver: str | None = None


class IngestHistoryResponse(BaseModel):
    items: list[IngestHistoryItem]
    control_boundary: ControlBoundaryModel = Field(default_factory=ControlBoundaryModel)


class OnboardingChecklistItem(BaseModel):
    key: Literal["network_model", "equipment_specs", "tag_mapping", "documents"]
    complete: bool
    count: int


class IngestOnboardingResponse(BaseModel):
    has_assets: bool
    progress: int
    checklist: list[OnboardingChecklistItem]
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
