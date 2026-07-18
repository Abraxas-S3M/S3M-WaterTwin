"""Strict tenant isolation for stored uploads.

Every upload is stored under a ``(tenant_id, upload_id)`` key. All reads —
listing, metadata, and content — require the caller's tenant to match the
upload's tenant; a mismatch raises :class:`CrossTenantAccessDenied` before any
data is returned. There is no "list all" or global content path: a caller can
only ever see its own tenant's uploads.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field


class CrossTenantAccessDenied(Exception):
    """Raised when a caller tries to access another tenant's upload."""

    def __init__(self, caller_tenant: str, owner_tenant: str, upload_id: str) -> None:
        super().__init__(
            f"tenant {caller_tenant!r} may not access upload {upload_id!r} owned by "
            f"tenant {owner_tenant!r}"
        )
        self.caller_tenant = caller_tenant
        self.owner_tenant = owner_tenant
        self.upload_id = upload_id


class UploadNotFound(Exception):
    """Raised when an upload id does not exist within the caller's tenant."""


@dataclass
class UploadRecord:
    """A stored upload's metadata and (until deleted) content."""

    upload_id: str
    tenant_id: str
    filename: str
    size_bytes: int
    content_sha256: str
    parser: str
    provenance: str
    approval_status: str
    residency_region: str
    uploaded_at: float
    uploaded_by: str
    parse_summary: dict[str, object] = field(default_factory=dict)
    injection_flags: tuple[str, ...] = ()
    content: bytes | None = None
    content_deleted: bool = False

    def metadata(self) -> dict[str, object]:
        """Return the tenant-safe metadata view (never the raw content)."""
        return {
            "upload_id": self.upload_id,
            "tenant_id": self.tenant_id,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "content_sha256": self.content_sha256,
            "parser": self.parser,
            "provenance": self.provenance,
            "approval_status": self.approval_status,
            "residency_region": self.residency_region,
            "uploaded_at": self.uploaded_at,
            "uploaded_by": self.uploaded_by,
            "parse_summary": self.parse_summary,
            "injection_flags": list(self.injection_flags),
            "content_deleted": self.content_deleted,
        }


class TenantStore:
    """In-memory, tenant-scoped upload store (thread-safe)."""

    def __init__(self) -> None:
        self._by_tenant: dict[str, dict[str, UploadRecord]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def new_upload_id() -> str:
        return f"upl-{uuid.uuid4().hex[:16]}"

    def put(self, record: UploadRecord) -> None:
        with self._lock:
            self._by_tenant.setdefault(record.tenant_id, {})[record.upload_id] = record

    def _owner_of(self, upload_id: str) -> str | None:
        for tenant_id, uploads in self._by_tenant.items():
            if upload_id in uploads:
                return tenant_id
        return None

    def get(self, caller_tenant: str, upload_id: str) -> UploadRecord:
        """Return a record iff it belongs to ``caller_tenant``.

        Raises :class:`CrossTenantAccessDenied` when the upload exists but under
        a different tenant, and :class:`UploadNotFound` when it does not exist at
        all. The two are distinguished so cross-tenant probing is explicitly
        refused (not masked as "not found", though either way no data leaks).
        """
        with self._lock:
            owner = self._owner_of(upload_id)
            if owner is None:
                raise UploadNotFound(upload_id)
            if owner != caller_tenant:
                raise CrossTenantAccessDenied(caller_tenant, owner, upload_id)
            return self._by_tenant[caller_tenant][upload_id]

    def get_content(self, caller_tenant: str, upload_id: str) -> bytes:
        """Return an upload's content, tenant-checked (raises if deleted)."""
        record = self.get(caller_tenant, upload_id)
        if record.content_deleted or record.content is None:
            raise UploadNotFound(f"{upload_id} content has been deleted")
        return record.content

    def list_for_tenant(self, caller_tenant: str) -> list[UploadRecord]:
        """Return only ``caller_tenant``'s uploads (never any other tenant's)."""
        with self._lock:
            return list(self._by_tenant.get(caller_tenant, {}).values())

    def delete_content(self, caller_tenant: str, upload_id: str) -> UploadRecord:
        """Delete an upload's *content* (metadata + audit history are retained)."""
        record = self.get(caller_tenant, upload_id)
        with self._lock:
            record.content = None
            record.content_deleted = True
        return record

    def all_records(self) -> list[UploadRecord]:
        """Admin/maintenance view across tenants (used by retention sweeps)."""
        with self._lock:
            return [rec for uploads in self._by_tenant.values() for rec in uploads.values()]
