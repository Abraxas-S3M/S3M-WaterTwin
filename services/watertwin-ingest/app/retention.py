"""Configurable per-tenant retention with documented deletion behaviour.

Retention answers two questions precisely:

* **What survives deletion?** The tamper-evident *audit entries* (upload
  received, scanned, parsed, approved, deleted). These are immutable history and
  are retained for the audit-retention period (regulatory), independent of
  content retention. They never contain file content — only metadata + hashes.
* **What does NOT survive deletion?** The uploaded *file content* and any derived
  parsed artifacts. When content is deleted (either on explicit request or when
  it ages past the tenant's retention period), the bytes are removed and the
  storage quota is returned; only a ``deleted`` audit event remains.

Retention periods are configured per tenant (defaulting to the platform
default). See ``docs/deployment/data-residency.md`` for the deployment view.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config

_SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True)
class RetentionPolicy:
    """A tenant's content-retention configuration."""

    tenant_id: str
    #: Days uploaded file *content* is retained before it becomes eligible for
    #: deletion. Audit entries are retained separately (see below).
    content_retention_days: int = config.DEFAULT_RETENTION_DAYS
    #: Days audit entries are retained (regulatory; typically much longer).
    audit_retention_days: int = 3650

    def content_expired(self, uploaded_at: float, *, now: float) -> bool:
        """True iff content uploaded at ``uploaded_at`` is past its retention."""
        age_days = (now - uploaded_at) / _SECONDS_PER_DAY
        return age_days >= self.content_retention_days


class RetentionRegistry:
    """Per-tenant retention policies with a documented default."""

    def __init__(self, default_days: int | None = None) -> None:
        self._default_days = (
            default_days if default_days is not None else config.DEFAULT_RETENTION_DAYS
        )
        self._policies: dict[str, RetentionPolicy] = {}

    def set_policy(self, policy: RetentionPolicy) -> None:
        self._policies[policy.tenant_id] = policy

    def policy_for(self, tenant_id: str) -> RetentionPolicy:
        if tenant_id in self._policies:
            return self._policies[tenant_id]
        return RetentionPolicy(
            tenant_id=tenant_id, content_retention_days=self._default_days
        )
