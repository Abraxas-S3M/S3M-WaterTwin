"""API-only shapes for the configuration service.

These describe the versioning + approval *wrapper* around the shared canonical
configuration content models. They are API/service concerns (request bodies, the
version record returned to clients, the lifecycle state machine) and so live in
the service rather than the shared canonical package.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ConfigStatus(str, Enum):
    """Lifecycle state of a configuration version.

    ``draft`` is the only mutable state; a version becomes immutable once it is
    submitted. Progression is strictly
    ``draft -> submitted -> approved -> active``; activating a version supersedes
    the previously active version of the same logical configuration.
    """

    draft = "draft"
    submitted = "submitted"
    approved = "approved"
    active = "active"
    superseded = "superseded"


#: Terminal / immutable states -- a version's payload can never change here.
IMMUTABLE_STATES: frozenset[ConfigStatus] = frozenset(
    {
        ConfigStatus.submitted,
        ConfigStatus.approved,
        ConfigStatus.active,
        ConfigStatus.superseded,
    }
)


class ConfigVersion(BaseModel):
    """One immutable version of a logical configuration entity."""

    version_id: str
    entity_type: str
    config_id: str
    version: int
    status: ConfigStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[str] = None
    created_at: str
    updated_at: str
    submitted_by: Optional[str] = None
    submitted_at: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    activated_at: Optional[str] = None
    superseded_by: Optional[str] = None


class ConfigCreateRequest(BaseModel):
    """Create a new draft version of a configuration entity.

    Omit ``config_id`` to start a new logical configuration keyed by the
    entity's natural key; provide it to start a *new draft version* of an
    existing configuration (the supersede-on-approve flow).
    """

    payload: dict[str, Any]
    config_id: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    """Replace the payload of an existing *draft* version."""

    payload: dict[str, Any]
