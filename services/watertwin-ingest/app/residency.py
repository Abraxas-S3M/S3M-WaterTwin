"""Data residency: per-tenant storage location for regulated jurisdictions.

Regulated customers — most importantly Saudi critical-infrastructure operators
subject to the National Cybersecurity Authority (NCA) and SAMA/PDPL data-
localisation rules — require that their uploaded content is stored in a specific
jurisdiction and never leaves it. Each tenant carries a residency region; the
ingest service refuses to place content outside a tenant's declared region.

This module holds the residency mapping and the check that a chosen storage
backend actually sits in the tenant's region. See
``docs/deployment/data-residency.md`` for the deployment-level configuration
(per-region storage backends, bucket/region tagging, and the Saudi CI profile).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config


class ResidencyViolation(Exception):
    """Raised when content would be stored outside a tenant's residency region."""


@dataclass(frozen=True)
class ResidencyPolicy:
    """A tenant's data-residency constraint."""

    tenant_id: str
    region: str
    #: When True the region is a hard requirement (regulated jurisdiction) and a
    #: mismatch is a violation; when False it is a preference.
    enforced: bool = True

    def assert_region_allowed(self, storage_region: str) -> None:
        """Raise :class:`ResidencyViolation` if ``storage_region`` is not allowed."""
        if self.enforced and storage_region.upper() != self.region.upper():
            raise ResidencyViolation(
                f"tenant {self.tenant_id!r} requires residency in "
                f"{self.region!r}; storage region {storage_region!r} is not allowed"
            )


class ResidencyRegistry:
    """Per-tenant residency policies with a documented default region."""

    def __init__(self, default_region: str | None = None) -> None:
        self._default_region = (default_region or config.DEFAULT_RESIDENCY_REGION).upper()
        self._policies: dict[str, ResidencyPolicy] = {}

    def set_policy(self, policy: ResidencyPolicy) -> None:
        self._policies[policy.tenant_id] = policy

    def policy_for(self, tenant_id: str) -> ResidencyPolicy:
        if tenant_id in self._policies:
            return self._policies[tenant_id]
        return ResidencyPolicy(
            tenant_id=tenant_id, region=self._default_region, enforced=True
        )

    def assert_storage_allowed(self, tenant_id: str, storage_region: str) -> None:
        self.policy_for(tenant_id).assert_region_allowed(storage_region)
