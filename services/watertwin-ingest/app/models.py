"""Data-intake models: parse results, proposed changes and AI analysis items.

Central safety rule expressed in the type system: a :class:`ProposedChange` that
originates from the AI path is constructed via :meth:`ProposedChange.from_draft`,
which forces ``ai_suggested=True`` and ``accepted=False`` and *clamps* the
proposed provenance so an AI draft can never outrank the source file it cites.
There is no code path in this module that sets ``accepted=True`` implicitly; a
human must call :meth:`ProposedChange.accept` per field.
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

import hashlib
import json
from typing import Any

from canonical_water_model import DataProvenance, now_iso
from pydantic import BaseModel, Field

# Trust ordering for provenance labels (higher rank = more trustworthy). Used to
# guarantee an AI-drafted value never carries a label that outranks its source.
_PROVENANCE_RANK: dict[DataProvenance, int] = {
    DataProvenance.synthetic: 0,
    DataProvenance.simulated: 1,
    DataProvenance.estimated: 2,
    DataProvenance.preliminary: 3,
    DataProvenance.measured: 4,
}

# The highest provenance an AI-derived value may ever claim. An AI inference is,
# at best, a preliminary engineering estimate; it can never be labelled
# ``measured`` no matter how trustworthy its source document is.
AI_PROVENANCE_CEILING = DataProvenance.preliminary


def provenance_rank(provenance: DataProvenance) -> int:
    """Return the trust rank of a provenance label (higher = more trusted)."""
    return _PROVENANCE_RANK[provenance]


def clamp_ai_provenance(source_provenance: DataProvenance) -> DataProvenance:
    """Clamp an AI-derived provenance to never outrank ``source_provenance``.

    The result is the *lower* of the source file's provenance and the AI ceiling
    (:data:`AI_PROVENANCE_CEILING`). This is the invariant that stops the AI from
    ever "raising a provenance label": a draft citing a ``measured`` nameplate is
    still only ``preliminary``, and a draft citing ``synthetic`` seed data stays
    ``synthetic``.
    """
    if provenance_rank(source_provenance) <= provenance_rank(AI_PROVENANCE_CEILING):
        return source_provenance
    return AI_PROVENANCE_CEILING


class SourceCitation(BaseModel):
    """A citation that points at a *specific* source location.

    Every AI-derived item must carry one so a reviewer can see exactly where a
    claim came from (which document, and where inside it).
    """

    document_id: str
    #: Human-readable locator inside the source (e.g. "sheet 'Curve', row 12",
    #: "page 3, nameplate table", "line 42").
    locator: str
    snippet: str | None = None


class ParsedField(BaseModel):
    """A single field the parser was able to extract from a staged file."""

    field_path: str
    value: Any
    unit: str | None = None
    citation: SourceCitation | None = None


class ParseResult(BaseModel):
    """The deterministic parser's output for one staged file.

    ``content`` is the untrusted file body; it is never interpolated into an S3M
    prompt directly — the analysis layer always wraps it in the delimited
    untrusted-data block (see :mod:`app.untrusted`).
    """

    ingest_id: str
    source_filename: str
    content_type: str
    #: Provenance of the *source file* itself. AI drafts derived from this file
    #: are clamped so they can never outrank it.
    source_provenance: DataProvenance = DataProvenance.preliminary
    content: str = ""
    parsed_fields: list[ParsedField] = Field(default_factory=list)
    #: Field paths the parser could not fill (candidates for AI drafting).
    unparsed_fields: list[str] = Field(default_factory=list)

    def content_hash(self) -> str:
        """A stable hash of the parse result used as the analysis cache key.

        Folds in the identity + the parsed/unparsed field structure + the raw
        content so any change to what would be analyzed changes the key.
        """
        material = {
            "ingest_id": self.ingest_id,
            "source_filename": self.source_filename,
            "content_type": self.content_type,
            "source_provenance": self.source_provenance.value,
            "content": self.content,
            "parsed_fields": [f.model_dump(mode="json") for f in self.parsed_fields],
            "unparsed_fields": sorted(self.unparsed_fields),
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ProposedChange(BaseModel):
    """One reviewable diff row.

    An AI-suggested change is always created via :meth:`from_draft`, which forces
    ``ai_suggested=True`` and ``accepted=False``. Acceptance is only ever set by
    :meth:`accept`, which represents an explicit, per-field human opt-in.
    """

    change_id: str
    field_path: str
    current_value: Any = None
    proposed_value: Any = None
    provenance: DataProvenance = DataProvenance.preliminary

    # --- AI badge -----------------------------------------------------------
    ai_suggested: bool = False
    ai_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ai_rationale: str | None = None
    citation: SourceCitation | None = None

    # --- Acceptance state (defaults to UNACCEPTED) --------------------------
    accepted: bool = False
    accepted_by: str | None = None
    accepted_at: str | None = None

    @classmethod
    def from_draft(
        cls,
        *,
        change_id: str,
        field_path: str,
        proposed_value: Any,
        ai_confidence: float,
        ai_rationale: str,
        citation: SourceCitation,
        source_provenance: DataProvenance,
        current_value: Any = None,
    ) -> ProposedChange:
        """Build an AI-suggested change that DEFAULTS TO UNACCEPTED.

        The provenance is clamped via :func:`clamp_ai_provenance` so the draft can
        never outrank the source file it was derived from.
        """
        return cls(
            change_id=change_id,
            field_path=field_path,
            current_value=current_value,
            proposed_value=proposed_value,
            provenance=clamp_ai_provenance(source_provenance),
            ai_suggested=True,
            ai_confidence=max(0.0, min(1.0, ai_confidence)),
            ai_rationale=ai_rationale,
            citation=citation,
            accepted=False,
            accepted_by=None,
            accepted_at=None,
        )

    def accept(self, operator: str) -> ProposedChange:
        """Record an explicit, per-field human opt-in for this change.

        This is the ONLY place ``accepted`` becomes ``True``. It requires a named
        operator; the AI path never calls it.
        """
        if not operator or not operator.strip():
            raise ValueError("accepting a proposed change requires a named operator")
        self.accepted = True
        self.accepted_by = operator
        self.accepted_at = now_iso()
        return self


class AnalysisSummary(BaseModel):
    """Plain-language summary of what a staged file contains."""

    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    citation: SourceCitation


class AnomalyFlag(BaseModel):
    """An anomaly cross-checked against existing canonical config.

    Advisory only: an anomaly flag never changes data or provenance; it is a
    cited observation a human must act on.
    """

    code: str
    message: str
    severity: str = "info"
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    citation: SourceCitation
    #: Canonical references the flag was cross-checked against (e.g. asset ids).
    cross_references: list[str] = Field(default_factory=list)


class DraftedValue(BaseModel):
    """A value the AI drafted for a field the parser could not fill."""

    field_path: str
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    citation: SourceCitation


class AnalysisResult(BaseModel):
    """The full analysis payload for one staged file.

    ``available`` is ``False`` when S3M-Core could not be reached; in that case
    the summary/anomalies/drafts are empty and the caller renders the plain diff
    with a quiet notice (graceful degradation).
    """

    ingest_id: str
    parse_result_hash: str
    available: bool = True
    notice: str | None = None
    model_version: str | None = None
    source_engine_status: str
    generated_at: str = Field(default_factory=now_iso)

    summary: AnalysisSummary | None = None
    anomalies: list[AnomalyFlag] = Field(default_factory=list)
    drafted_values: list[DraftedValue] = Field(default_factory=list)
    #: AI-suggested diff rows (always ``accepted=False`` on arrival).
    proposed_changes: list[ProposedChange] = Field(default_factory=list)
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
