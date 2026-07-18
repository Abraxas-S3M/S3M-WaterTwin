"""IngestService: the facade that runs every security control on an upload.

The pipeline for an accepted upload, in order:

1. **Deployment gate** — reject if ingestion is disabled (one-way diode).
2. **Quota** — per-tenant file-size, rate and storage quotas (fail loudly).
3. **Malware scan** — reject known-bad content (EICAR/AV).
4. **Provenance** — stamp the immutable ``customer-upload`` provenance and flag
   any prompt-injection markers for a human (no action taken).
5. **Residency** — confirm the tenant's storage region is allowed.
6. **Sandboxed parse** — parse in a resource-capped child (timeout + memory cap).
7. **Store + audit** — persist under strict tenant isolation and append the
   tamper-evident audit events (received -> scanned -> parsed -> stored).

Reads (list/get/content), approval and deletion are all tenant-checked and
audited. Nothing in this service is a control-write path.
"""

from __future__ import annotations

import hashlib
import time

from . import config, deployment
from .audit import AuditLog
from .control_boundary import CONTROL_BOUNDARY, safety_invariant_intact
from .provenance import record_for_upload
from .quotas import QuotaManager
from .residency import ResidencyRegistry
from .retention import RetentionRegistry
from .scanning import assert_clean
from .tenancy import TenantStore, UploadRecord


class IngestService:
    """Ties together quotas, scanning, sandboxed parsing, tenancy and audit."""

    def __init__(
        self,
        *,
        store: TenantStore | None = None,
        quotas: QuotaManager | None = None,
        retention: RetentionRegistry | None = None,
        residency: ResidencyRegistry | None = None,
        audit: AuditLog | None = None,
        profile: str | None = None,
    ) -> None:
        self.store = store or TenantStore()
        self.quotas = quotas or QuotaManager()
        self.retention = retention or RetentionRegistry()
        self.residency = residency or ResidencyRegistry()
        self.audit = audit or AuditLog()
        self._profile = deployment.get_profile(profile)

    # -- capabilities / posture --------------------------------------------- #

    def capabilities(self) -> dict[str, object]:
        """Report what the dashboard should render + the fixed safety posture."""
        enabled = deployment.ingestion_enabled(self._profile)
        return {
            "service": config.SERVICE_NAME,
            "version": config.SERVICE_VERSION,
            "deployment_profile": self._profile,
            "ingestion_enabled": enabled,
            # The dashboard hides the nav item when ingestion is disabled.
            "nav": {"ingestion": {"visible": deployment.nav_item_visible(self._profile)}},
            "safety_invariant_intact": safety_invariant_intact(),
            "control_boundary": CONTROL_BOUNDARY.as_dict(),
            "optional": True,  # the platform is fully functional without ingest
        }

    # -- upload pipeline ---------------------------------------------------- #

    def upload(
        self,
        *,
        tenant_id: str,
        uploaded_by: str,
        filename: str,
        data: bytes,
        parser: str,
        storage_region: str | None = None,
        now: float | None = None,
    ) -> UploadRecord:
        """Run the full control pipeline and store the upload (or raise)."""
        now = time.time() if now is None else now

        # 1. Deployment gate.
        deployment.assert_ingestion_enabled(self._profile)

        # 2. Quotas (fail loudly, before doing any work).
        self.quotas.check_upload(tenant_id, len(data), now=now)

        upload_id = self.store.new_upload_id()
        self.audit.append(
            kind="upload.received",
            actor=uploaded_by,
            subject=upload_id,
            tenant_id=tenant_id,
            payload={"filename": filename, "size_bytes": len(data)},
        )

        # 3. Malware scan.
        assert_clean(data)
        self.audit.append(
            kind="upload.scanned",
            actor="ingest-scanner",
            subject=upload_id,
            tenant_id=tenant_id,
            payload={"clean": True},
        )

        # 4. Provenance + prompt-injection flagging (advisory only).
        prov = record_for_upload(data)

        # 5. Residency.
        region = (storage_region or self.residency.policy_for(tenant_id).region).upper()
        self.residency.assert_storage_allowed(tenant_id, region)

        # 6. Sandboxed parse (timeout + memory cap). Import lazily so the module
        #    graph stays small for callers that never parse.
        from .limits import run_sandboxed

        self.quotas.acquire_job_slot(tenant_id)
        try:
            parse_summary = run_sandboxed(parser, data)
        finally:
            self.quotas.release_job_slot(tenant_id)

        # 7. Store + record.
        digest = hashlib.sha256(data).hexdigest()
        record = UploadRecord(
            upload_id=upload_id,
            tenant_id=tenant_id,
            filename=filename,
            size_bytes=len(data),
            content_sha256=digest,
            parser=parser,
            provenance=prov.provenance,
            approval_status=prov.approval_status,
            residency_region=region,
            uploaded_at=now,
            uploaded_by=uploaded_by,
            parse_summary=parse_summary,
            injection_flags=prov.injection_flags,
            content=data,
        )
        self.store.put(record)
        self.quotas.record_upload(tenant_id, len(data), now=now)
        self.audit.append(
            kind="upload.parsed",
            actor="ingest-parser",
            subject=upload_id,
            tenant_id=tenant_id,
            payload={
                "content_sha256": digest,
                "parser": parser,
                "parse_summary": parse_summary,
                "injection_flags": list(prov.injection_flags),
                "provenance": prov.provenance,
                "approval_status": prov.approval_status,
            },
        )
        return record

    # -- reads (tenant-checked) --------------------------------------------- #

    def list_uploads(self, *, caller_tenant: str) -> list[dict[str, object]]:
        return [r.metadata() for r in self.store.list_for_tenant(caller_tenant)]

    def get_metadata(self, *, caller_tenant: str, upload_id: str) -> dict[str, object]:
        return self.store.get(caller_tenant, upload_id).metadata()

    def get_content(self, *, caller_tenant: str, upload_id: str) -> bytes:
        return self.store.get_content(caller_tenant, upload_id)

    # -- approval (human-only, never a control write) ----------------------- #

    def approve(
        self, *, caller_tenant: str, upload_id: str, approver: str, decision: str
    ) -> dict[str, object]:
        """Record a human approval decision (advisory; never a control write)."""
        if decision not in ("approved", "rejected"):
            raise ValueError("decision must be 'approved' or 'rejected'")
        record = self.store.get(caller_tenant, upload_id)
        record.approval_status = decision
        self.audit.append(
            kind="upload.approval",
            actor=approver,
            subject=upload_id,
            tenant_id=caller_tenant,
            payload={
                "decision": decision,
                "control_write_enabled": CONTROL_BOUNDARY.control_write_enabled,
            },
        )
        return record.metadata()

    # -- deletion (content only; audit survives) ---------------------------- #

    def delete_content(
        self, *, caller_tenant: str, upload_id: str, actor: str
    ) -> dict[str, object]:
        """Delete file content; retain immutable audit history."""
        record = self.store.get(caller_tenant, upload_id)
        size = record.size_bytes
        self.store.delete_content(caller_tenant, upload_id)
        self.quotas.release_storage(caller_tenant, size)
        self.audit.append(
            kind="upload.deleted",
            actor=actor,
            subject=upload_id,
            tenant_id=caller_tenant,
            payload={"content_deleted": True, "content_sha256": record.content_sha256},
        )
        return record.metadata()

    # -- retention sweep ---------------------------------------------------- #

    def sweep_retention(self, *, now: float | None = None) -> list[str]:
        """Delete content past each tenant's retention; return deleted ids."""
        now = time.time() if now is None else now
        deleted: list[str] = []
        for record in self.store.all_records():
            if record.content_deleted:
                continue
            policy = self.retention.policy_for(record.tenant_id)
            if policy.content_expired(record.uploaded_at, now=now):
                self.delete_content(
                    caller_tenant=record.tenant_id,
                    upload_id=record.upload_id,
                    actor="retention-sweep",
                )
                deleted.append(record.upload_id)
        return deleted

    # -- audit -------------------------------------------------------------- #

    def audit_trail(self, *, caller_tenant: str, upload_id: str) -> list[dict[str, object]]:
        return self.audit.subject_trail(upload_id, tenant_id=caller_tenant)

    def verify_audit(self) -> dict[str, object]:
        return self.audit.verify()
