"""Pydantic DTOs for the watertwin-ingest API.

These mirror the TypeScript ingest types consumed by the dashboard
(``apps/dashboard/src/api/types.ts``). Everything here is declarative data;
nothing describes or triggers a control action.
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
