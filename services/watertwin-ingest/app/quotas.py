"""Per-tenant rate limits and quotas (fail loudly, never silently).

Three independent quotas are enforced per tenant:

* **Uploads per hour** — a rolling-window rate limit on upload count.
* **Total storage bytes** — the cumulative retained size across all uploads.
* **Concurrent parse jobs** — how many parse jobs a tenant may run at once.

Every quota breach raises :class:`QuotaExceeded` with a machine-readable
``quota`` field and a clear message. Nothing is dropped silently: the caller
(and the audit trail) always learns exactly which quota was hit and by how much.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class TenantQuota:
    """The quota limits applied to a single tenant."""

    max_uploads_per_hour: int = config.MAX_UPLOADS_PER_HOUR
    max_storage_bytes: int = config.MAX_STORAGE_BYTES_PER_TENANT
    max_concurrent_parse_jobs: int = config.MAX_CONCURRENT_PARSE_JOBS
    max_upload_bytes: int = config.MAX_UPLOAD_BYTES


class QuotaExceeded(Exception):
    """Raised when a tenant exceeds one of its quotas (never silent)."""

    def __init__(self, quota: str, limit: float, observed: float, message: str) -> None:
        super().__init__(message)
        self.quota = quota
        self.limit = limit
        self.observed = observed

    def as_dict(self) -> dict[str, object]:
        return {
            "error": "quota_exceeded",
            "quota": self.quota,
            "limit": self.limit,
            "observed": self.observed,
            "message": str(self),
        }


_WINDOW_SECONDS = 3600.0


class QuotaManager:
    """Thread-safe per-tenant quota accounting."""

    def __init__(self, default_quota: TenantQuota | None = None) -> None:
        self._default = default_quota or TenantQuota()
        self._overrides: dict[str, TenantQuota] = {}
        self._upload_times: dict[str, deque[float]] = defaultdict(deque)
        self._storage_bytes: dict[str, int] = defaultdict(int)
        self._active_jobs: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def set_quota(self, tenant_id: str, quota: TenantQuota) -> None:
        with self._lock:
            self._overrides[tenant_id] = quota

    def quota_for(self, tenant_id: str) -> TenantQuota:
        return self._overrides.get(tenant_id, self._default)

    def _prune(self, tenant_id: str, now: float) -> None:
        window = self._upload_times[tenant_id]
        cutoff = now - _WINDOW_SECONDS
        while window and window[0] < cutoff:
            window.popleft()

    def check_upload(
        self, tenant_id: str, size_bytes: int, *, now: float | None = None
    ) -> None:
        """Raise :class:`QuotaExceeded` if accepting this upload breaks a quota.

        Checks single-file size, rolling upload rate, and total storage. Does not
        mutate state; call :meth:`record_upload` once the upload is accepted.
        """
        now = time.time() if now is None else now
        quota = self.quota_for(tenant_id)
        if size_bytes > quota.max_upload_bytes:
            raise QuotaExceeded(
                "upload_bytes",
                quota.max_upload_bytes,
                size_bytes,
                f"upload of {size_bytes} bytes exceeds per-file cap of "
                f"{quota.max_upload_bytes} bytes",
            )
        with self._lock:
            self._prune(tenant_id, now)
            count = len(self._upload_times[tenant_id])
            if count >= quota.max_uploads_per_hour:
                raise QuotaExceeded(
                    "uploads_per_hour",
                    quota.max_uploads_per_hour,
                    count + 1,
                    f"tenant {tenant_id!r} exceeded {quota.max_uploads_per_hour} "
                    "uploads per hour",
                )
            projected = self._storage_bytes[tenant_id] + size_bytes
            if projected > quota.max_storage_bytes:
                raise QuotaExceeded(
                    "storage_bytes",
                    quota.max_storage_bytes,
                    projected,
                    f"tenant {tenant_id!r} storage would reach {projected} bytes, "
                    f"over the {quota.max_storage_bytes}-byte cap",
                )

    def record_upload(
        self, tenant_id: str, size_bytes: int, *, now: float | None = None
    ) -> None:
        """Record an accepted upload against the tenant's rate + storage quota."""
        now = time.time() if now is None else now
        with self._lock:
            self._prune(tenant_id, now)
            self._upload_times[tenant_id].append(now)
            self._storage_bytes[tenant_id] += size_bytes

    def release_storage(self, tenant_id: str, size_bytes: int) -> None:
        """Return ``size_bytes`` to a tenant's storage budget (on deletion)."""
        with self._lock:
            self._storage_bytes[tenant_id] = max(
                0, self._storage_bytes[tenant_id] - size_bytes
            )

    def storage_used(self, tenant_id: str) -> int:
        with self._lock:
            return self._storage_bytes[tenant_id]

    def acquire_job_slot(self, tenant_id: str) -> None:
        """Reserve a concurrent-parse slot or raise :class:`QuotaExceeded`."""
        quota = self.quota_for(tenant_id)
        with self._lock:
            active = self._active_jobs[tenant_id]
            if active >= quota.max_concurrent_parse_jobs:
                raise QuotaExceeded(
                    "concurrent_parse_jobs",
                    quota.max_concurrent_parse_jobs,
                    active + 1,
                    f"tenant {tenant_id!r} already has {active} concurrent parse "
                    f"jobs (max {quota.max_concurrent_parse_jobs})",
                )
            self._active_jobs[tenant_id] = active + 1

    def release_job_slot(self, tenant_id: str) -> None:
        with self._lock:
            self._active_jobs[tenant_id] = max(0, self._active_jobs[tenant_id] - 1)

    def active_jobs(self, tenant_id: str) -> int:
        with self._lock:
            return self._active_jobs[tenant_id]
