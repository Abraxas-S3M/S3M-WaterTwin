"""watertwin-ingest FastAPI application.

Endpoints (all under ``/api/v1/ingest``) implement the five-state Data Intake
flow: status, classify, preview, submit, history, approve, plus an onboarding
summary. The service is advisory and read-only to OT; the only writes it makes
are drafts created through watertwin-api's existing configuration lifecycle, all
of which require human approval. Separation of duties is enforced here in
:func:`submit` / :func:`approve`, not merely in the UI.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse

from . import epanet, sod
from .config_client import (
    ConfigError,
    ConfigLifecycleClient,
    HttpConfigClient,
    InMemoryConfigClient,
)
from .models import (
    ControlBoundaryModel,
    IngestAcceptedType,
    IngestClassification,
    IngestClassifyRequest,
    IngestCreatedVersion,
    IngestDiffGroup,
    IngestDiffRow,
    IngestEntityCount,
    IngestHistoryItem,
    IngestHistoryResponse,
    IngestOnboardingResponse,
    IngestPreview,
    IngestStatusResponse,
    IngestSubmitRequest,
    IngestSubmitResult,
    IngestUnparsedRow,
    OnboardingChecklistItem,
)
from .store import IngestStore, Upload

# Deployment profiles in which the intake surface is disabled entirely. When the
# profile disables ingest the dashboard hides the nav entry and shows a clear
# unavailable state.
DISABLED_PROFILES = {"edge", "airgapped-viewer"}

MAX_INP_BYTES = 5_000_000

ACCEPTED_TYPES = [
    IngestAcceptedType(
        extension=".inp", label="EPANET network model", max_bytes=MAX_INP_BYTES
    ),
]

app = FastAPI(
    title="watertwin-ingest",
    version="0.1.0",
    description="Advisory file-intake service (read-only to OT).",
)

store = IngestStore()


def _make_config_client() -> ConfigLifecycleClient:
    base = os.environ.get("WATERTWIN_API_BASE")
    if base:
        return HttpConfigClient(base, token=os.environ.get("WATERTWIN_API_TOKEN"))
    return InMemoryConfigClient()


config_client: ConfigLifecycleClient = _make_config_client()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _deployment_profile() -> str:
    return os.environ.get("DEPLOYMENT_PROFILE", "standard")


def _ingest_available() -> bool:
    enabled = os.environ.get("INGEST_ENABLED", "true").lower() != "false"
    return enabled and _deployment_profile() not in DISABLED_PROFILES


class Principal:
    def __init__(self, actor: str, roles: list[str]) -> None:
        self.actor = actor
        self.roles = roles

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


def current_principal(
    x_actor: str | None = Header(default=None),
    x_roles: str | None = Header(default=None),
) -> Principal:
    """Resolve the caller.

    The ingest service sits behind the authenticated API gateway; the gateway
    forwards the verified identity via ``X-Actor``/``X-Roles``. When unset (local
    dev), fall back to a synthetic engineer so the service is usable without a
    gateway — never a control identity, since the service issues no control.
    """
    actor = x_actor or "dev-engineer"
    roles = [r.strip() for r in (x_roles or "engineer").split(",") if r.strip()]
    return Principal(actor=actor, roles=roles)


def _boundary() -> ControlBoundaryModel:
    return ControlBoundaryModel()


# --- diffing ---------------------------------------------------------------- #

_CRITICALITY = {"hp_pump": "critical", "control_valve": "high"}


def _asset_payload(
    asset_id: str, name: str, asset_type: str, facility_id: str
) -> dict:
    return {
        "asset_id": asset_id,
        "name": name,
        "asset_type": asset_type,
        "facility_id": facility_id,
        "train_id": "RO-TRAIN-001",
        "criticality": _CRITICALITY.get(asset_type, "medium"),
    }


def _build_diff(
    network: epanet.ParsedNetwork,
    facility_id: str,
    existing_asset_ids: set[str],
) -> tuple[list[IngestDiffGroup], dict[tuple[str, str], dict], list[IngestEntityCount]]:
    rows: list[IngestDiffRow] = []
    payloads: dict[tuple[str, str], dict] = {}

    for section, asset_type in epanet.ASSET_SECTIONS.items():
        for element in network.by_section(section):
            asset_id = element.element_id
            change_type = "update" if asset_id in existing_asset_ids else "new"
            current_name = asset_id if change_type == "update" else None
            payloads[("asset", asset_id)] = _asset_payload(
                asset_id, asset_id, asset_type, facility_id
            )
            source = f"[{section}] line {element.line}"
            rows.append(
                IngestDiffRow(
                    row_id=f"{asset_id}:asset_type",
                    entity="asset",
                    config_id=asset_id,
                    field="asset_type",
                    current_value=None if change_type == "new" else asset_type,
                    proposed_value=asset_type,
                    source_ref=source,
                    provenance="preliminary",
                    change_type=change_type,
                    match_confidence=0.9,
                    safety_relevant=sod.is_safety_relevant("asset"),
                )
            )
            rows.append(
                IngestDiffRow(
                    row_id=f"{asset_id}:name",
                    entity="asset",
                    config_id=asset_id,
                    field="name",
                    current_value=current_name,
                    proposed_value=asset_id,
                    source_ref=source,
                    provenance="preliminary",
                    change_type=change_type,
                    match_confidence=0.9,
                    safety_relevant=sod.is_safety_relevant("asset"),
                )
            )

    groups: list[IngestDiffGroup] = []
    if rows:
        groups.append(
            IngestDiffGroup(panel="asset-hierarchy", label="Asset Hierarchy", rows=rows)
        )

    counts: list[IngestEntityCount] = []
    for section in epanet.COUNTED_SECTIONS:
        elements = network.by_section(section)
        found = len(elements)
        if found == 0:
            continue
        if section in epanet.ASSET_SECTIONS:
            matched = sum(1 for e in elements if e.element_id in existing_asset_ids)
        else:
            matched = 0
        counts.append(
            IngestEntityCount(
                entity=section.lower(),
                label=section.title(),
                found=found,
                matched=matched,
                added=found - matched,
                conflicts=0,
            )
        )

    return groups, payloads, counts


# --- endpoints -------------------------------------------------------------- #


@app.post("/api/v1/reset")
def reset() -> dict:
    """Reset in-memory state (test/dev only)."""
    store.reset()
    global config_client
    config_client = _make_config_client()
    return {"ok": True}


@app.get("/api/v1/ingest/status", response_model=IngestStatusResponse)
def status() -> IngestStatusResponse:
    return IngestStatusResponse(
        available=_ingest_available(),
        enabled=os.environ.get("INGEST_ENABLED", "true").lower() != "false",
        deployment_profile=_deployment_profile(),
        accepted_types=ACCEPTED_TYPES,
        control_boundary=_boundary(),
    )


@app.get("/api/v1/ingest/onboarding", response_model=IngestOnboardingResponse)
def onboarding() -> IngestOnboardingResponse:
    assets = config_client.active_config_ids("asset")
    equipment = config_client.active_config_ids("rated_equipment")
    tags = config_client.active_config_ids("tag_mapping")
    checklist = [
        OnboardingChecklistItem(
            key="network_model", complete=bool(assets), count=len(assets)
        ),
        OnboardingChecklistItem(
            key="equipment_specs", complete=bool(equipment), count=len(equipment)
        ),
        OnboardingChecklistItem(
            key="tag_mapping", complete=bool(tags), count=len(tags)
        ),
        OnboardingChecklistItem(key="documents", complete=False, count=0),
    ]
    done = sum(1 for c in checklist if c.complete)
    progress = round(100 * done / len(checklist))
    return IngestOnboardingResponse(
        has_assets=bool(assets), progress=progress, checklist=checklist
    )


@app.post("/api/v1/ingest/classify", response_model=IngestClassification)
def classify(
    body: IngestClassifyRequest,
    principal: Principal = Depends(current_principal),
) -> IngestClassification:
    if not _ingest_available():
        raise HTTPException(status_code=503, detail="ingest service is unavailable")
    if body.size_bytes > MAX_INP_BYTES:
        raise HTTPException(status_code=413, detail="file exceeds the size limit")

    sha = hashlib.sha256(body.content.encode("utf-8")).hexdigest()
    upload_id = str(uuid.uuid4())
    is_epanet, confidence, detail = epanet.looks_like_epanet(body.content)
    suggested = body.confirmed_class or ("epanet_inp" if is_epanet else "unknown")

    facility_id = (body.scope.facility_id if body.scope else None) or "S3M-DESAL-01"
    network = epanet.parse_inp(body.content)
    groups, payloads, counts = _build_diff(
        network, facility_id, config_client.active_config_ids("asset")
    )
    unparsed = [
        IngestUnparsedRow(line=u.line, section=u.section, raw=u.raw, reason=u.reason)
        for u in network.unparsed
    ]

    upload = Upload(
        upload_id=upload_id,
        filename=body.filename,
        sha256=sha,
        size_bytes=body.size_bytes,
        uploader=principal.actor,
        timestamp=_now_iso(),
        upload_class=suggested,
        status="classified",
        content=body.content,
        payloads=payloads,
        diff=groups,
        entity_counts=counts,
        unparsed=unparsed,
    )
    store.put(upload)

    return IngestClassification(
        upload_id=upload_id,
        filename=body.filename,
        sha256=sha,
        size_bytes=body.size_bytes,
        suggested_class=suggested,
        confidence=confidence,
        detail=detail,
        supported_classes=["epanet_inp", "unknown"],
    )


@app.get("/api/v1/ingest/uploads/{upload_id}/preview", response_model=IngestPreview)
def preview(upload_id: str) -> IngestPreview:
    upload = store.get(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="unknown upload")
    if upload.status == "classified":
        upload.status = "previewed"
    return IngestPreview(
        upload_id=upload.upload_id,
        status="ready",
        suggested_class=upload.upload_class,
        entity_counts=upload.entity_counts,
        unparsed=upload.unparsed,
        diff=upload.diff,
    )


@app.post("/api/v1/ingest/submit", response_model=IngestSubmitResult)
def submit(
    body: IngestSubmitRequest,
    principal: Principal = Depends(current_principal),
) -> IngestSubmitResult:
    upload = store.get(body.upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="unknown upload")

    accepted = {d.row_id for d in body.decisions if d.accepted}
    rejected = [d for d in body.decisions if not d.accepted]

    # A config version is a whole object; a config id is submitted when any of
    # its field-level rows was accepted.
    accepted_config_ids: dict[str, str] = {}
    for group in upload.diff:
        for row in group.rows:
            if row.row_id in accepted:
                accepted_config_ids[row.config_id] = row.entity

    created: list[IngestCreatedVersion] = []
    touched_entities: set[str] = set()
    for config_id, entity in accepted_config_ids.items():
        payload = upload.payloads.get((entity, config_id))
        if payload is None:
            continue
        try:
            version = config_client.create_and_submit(
                entity, config_id, payload, body.actor
            )
        except ConfigError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        touched_entities.add(entity)
        created.append(
            IngestCreatedVersion(
                entity=entity,
                config_id=config_id,
                version=version["version"],
                version_id=version["version_id"],
                status=version["status"],
            )
        )

    needs_separate = sod.requires_separate_approver(touched_entities)
    upload.status = "submitted"
    upload.submitter = body.actor
    if created:
        upload.config_version = max(v.version for v in created)

    message = (
        "Draft created and submitted for approval."
        if not needs_separate
        else "Draft created; a separate approver is required (separation of duties)."
    )
    return IngestSubmitResult(
        upload_id=upload.upload_id,
        created_versions=created,
        accepted_count=len(accepted_config_ids),
        rejected_count=len(rejected),
        requires_separate_approver=needs_separate,
        self_approval_blocked=needs_separate,
        blocked_entities=sod.blocked_entities(touched_entities),
        message=message,
        control_boundary=_boundary(),
    )


@app.post("/api/v1/ingest/uploads/{upload_id}/approve", response_model=IngestSubmitResult)
def approve(
    upload_id: str,
    principal: Principal = Depends(current_principal),
) -> IngestSubmitResult:
    upload = store.get(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="unknown upload")

    touched_entities = {entity for (entity, _cid) in upload.payloads}
    # SEPARATION OF DUTIES: for safety-relevant entities the submitter may not
    # approve their own submission. Enforced server-side.
    if sod.requires_separate_approver(touched_entities) and principal.actor == upload.submitter:
        raise HTTPException(
            status_code=403,
            detail=(
                "Separation of duties: the submitter cannot approve a change that "
                "touches asset hierarchy, rated equipment, or alarm thresholds."
            ),
        )

    created: list[IngestCreatedVersion] = []
    accepted_ids = {
        (row.entity, row.config_id)
        for group in upload.diff
        for row in group.rows
    }
    for entity, config_id in sorted(accepted_ids):
        try:
            version = config_client.approve(entity, config_id, principal.actor)
        except ConfigError:
            continue
        created.append(
            IngestCreatedVersion(
                entity=entity,
                config_id=config_id,
                version=version["version"],
                version_id=version["version_id"],
                status=version["status"],
            )
        )

    upload.status = "approved"
    upload.approver = principal.actor
    return IngestSubmitResult(
        upload_id=upload.upload_id,
        created_versions=created,
        accepted_count=len(created),
        rejected_count=0,
        requires_separate_approver=False,
        self_approval_blocked=False,
        blocked_entities=[],
        message="Approved and activated.",
        control_boundary=_boundary(),
    )


@app.get("/api/v1/ingest/history", response_model=IngestHistoryResponse)
def history() -> IngestHistoryResponse:
    items = [
        IngestHistoryItem(
            upload_id=u.upload_id,
            filename=u.filename,
            sha256=u.sha256,
            uploader=u.uploader,
            timestamp=u.timestamp,
            upload_class=u.upload_class,
            status=u.status,  # type: ignore[arg-type]
            config_version=u.config_version,
            approver=u.approver,
        )
        for u in store.all()
    ]
    return IngestHistoryResponse(items=items, control_boundary=_boundary())


@app.get("/api/v1/ingest/uploads/{upload_id}/original", response_class=PlainTextResponse)
def original(
    upload_id: str,
    principal: Principal = Depends(current_principal),
) -> PlainTextResponse:
    # Original-file download is admin-only (enforced server-side).
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="original download requires the admin role")
    upload = store.get(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="unknown upload")
    return PlainTextResponse(
        upload.content,
        headers={"Content-Disposition": f'attachment; filename="{upload.filename}"'},
    )
