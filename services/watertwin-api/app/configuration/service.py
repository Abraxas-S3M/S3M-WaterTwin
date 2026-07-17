"""Versioned, approval-gated customer configuration service.

Implements the configuration lifecycle on top of the existing persistence layer
(:class:`app.store.Store`, TimescaleDB with in-memory fallback) and the
tamper-evident audit hash chain (``store.audit`` / :mod:`app.audit`).

Lifecycle (each transition appends an audit event):

    draft --publish--> submitted --approve--> approved --(auto)--> active

* A version's ``payload`` is only mutable while it is a ``draft``
  (immutable-on-publish).
* Approving a version activates it and **supersedes** the previously active
  version of the same logical configuration -- published versions are never
  deleted, only superseded.

Nothing here writes to any control system; configuration is declarative data and
never touches a control path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from canonical_water_model import TagMappingConfig

from ..store import Store
from ..tag_normalization import TagMap
from . import entities
from .models import ConfigStatus, ConfigVersion


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class ConfigError(Exception):
    """Base error for configuration operations."""

    status_code = 400


class UnknownEntityError(ConfigError):
    status_code = 404


class ConfigNotFoundError(ConfigError):
    status_code = 404


class ConfigValidationError(ConfigError):
    status_code = 422


class ConfigConflictError(ConfigError):
    status_code = 409


class ConfigService:
    """Configuration lifecycle operations bound to a shared :class:`Store`."""

    def __init__(self, store: Store) -> None:
        self._store = store

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def entity_types() -> list[str]:
        return entities.entity_types()

    def _require_entity(self, entity_type: str) -> None:
        if not entities.is_known_entity(entity_type):
            raise UnknownEntityError(
                f"unknown config entity '{entity_type}'; known: {entities.entity_types()}"
            )

    def _validate(self, entity_type: str, payload: dict[str, Any]):
        model_cls = entities.model_for(entity_type)
        try:
            model = model_cls.model_validate(payload)
        except ValidationError as exc:
            raise ConfigValidationError(
                f"invalid {entity_type} payload: {exc.errors(include_url=False)}"
            ) from exc
        return model, model.model_dump(mode="json")

    def _audit(self, kind: str, record: dict[str, Any], actor: str, **extra: Any) -> None:
        self._store.audit(
            kind,
            payload={
                "entity_type": record["entity_type"],
                "config_id": record["config_id"],
                "version": record["version"],
                "version_id": record["version_id"],
                "status": record["status"],
                **extra,
            },
            actor=actor,
            subject=record["version_id"],
        )

    def _latest(self, entity_type: str, config_id: str) -> dict[str, Any] | None:
        versions = self._store.list_config_versions(entity_type, config_id)
        return versions[-1] if versions else None

    # -- reads ----------------------------------------------------------------

    def list_active(self, entity_type: str) -> list[ConfigVersion]:
        self._require_entity(entity_type)
        return [ConfigVersion(**r) for r in self._store.list_config_active(entity_type)]

    def list_versions(self, entity_type: str, config_id: str) -> list[ConfigVersion]:
        self._require_entity(entity_type)
        rows = self._store.list_config_versions(entity_type, config_id)
        if not rows:
            raise ConfigNotFoundError(
                f"no {entity_type} configuration with id '{config_id}'"
            )
        return [ConfigVersion(**r) for r in rows]

    def get_version(self, version_id: str) -> ConfigVersion:
        row = self._store.get_config_version(version_id)
        if row is None:
            raise ConfigNotFoundError(f"unknown config version '{version_id}'")
        return ConfigVersion(**row)

    def get_active(self, entity_type: str, config_id: str) -> ConfigVersion:
        """Return the active version, else the latest version, for a config id."""
        self._require_entity(entity_type)
        rows = self._store.list_config_versions(entity_type, config_id)
        if not rows:
            raise ConfigNotFoundError(
                f"no {entity_type} configuration with id '{config_id}'"
            )
        for row in rows:
            if row["status"] == ConfigStatus.active.value:
                return ConfigVersion(**row)
        return ConfigVersion(**rows[-1])

    # -- writes ---------------------------------------------------------------

    def create(
        self,
        entity_type: str,
        payload: dict[str, Any],
        actor: str,
        config_id: str | None = None,
    ) -> ConfigVersion:
        """Create a new ``draft`` version of a configuration entity."""
        self._require_entity(entity_type)
        model, canonical = self._validate(entity_type, payload)
        logical_id = config_id or entities.natural_key(entity_type, model)

        existing = self._store.list_config_versions(entity_type, logical_id)
        # Refuse to start a new draft while a version is still in-flight; the
        # in-flight version must be completed (approved/active) or the caller
        # should edit the existing draft instead.
        for row in existing:
            if row["status"] in {
                ConfigStatus.draft.value,
                ConfigStatus.submitted.value,
                ConfigStatus.approved.value,
            }:
                raise ConfigConflictError(
                    f"{entity_type} '{logical_id}' already has an in-flight version "
                    f"(v{row['version']}, status={row['status']}); finish or edit it first"
                )
        version_no = (existing[-1]["version"] + 1) if existing else 1

        now = _utcnow_iso()
        record = {
            "version_id": str(uuid.uuid4()),
            "entity_type": entity_type,
            "config_id": logical_id,
            "version": version_no,
            "status": ConfigStatus.draft.value,
            "payload": canonical,
            "created_by": actor,
            "created_at": now,
            "updated_at": now,
            "submitted_by": None,
            "submitted_at": None,
            "approved_by": None,
            "approved_at": None,
            "activated_at": None,
            "superseded_by": None,
        }
        stored = self._store.save_config_version(record)
        self._audit("config.created", stored, actor)
        return ConfigVersion(**stored)

    def update(
        self, entity_type: str, config_id: str, payload: dict[str, Any], actor: str
    ) -> ConfigVersion:
        """Replace the payload of the current ``draft`` version."""
        self._require_entity(entity_type)
        latest = self._latest(entity_type, config_id)
        if latest is None:
            raise ConfigNotFoundError(
                f"no {entity_type} configuration with id '{config_id}'"
            )
        if latest["status"] != ConfigStatus.draft.value:
            raise ConfigConflictError(
                f"{entity_type} '{config_id}' v{latest['version']} is "
                f"{latest['status']} and immutable; create a new draft version to change it"
            )
        _model, canonical = self._validate(entity_type, payload)
        now = _utcnow_iso()
        self._store.update_config_version(
            latest["version_id"], {"payload": canonical, "updated_at": now}
        )
        latest.update({"payload": canonical, "updated_at": now})
        self._audit("config.updated", latest, actor)
        return ConfigVersion(**latest)

    def publish(self, entity_type: str, config_id: str, actor: str) -> ConfigVersion:
        """Submit the current draft for approval (draft -> submitted; locks it)."""
        self._require_entity(entity_type)
        latest = self._latest(entity_type, config_id)
        if latest is None:
            raise ConfigNotFoundError(
                f"no {entity_type} configuration with id '{config_id}'"
            )
        if latest["status"] != ConfigStatus.draft.value:
            raise ConfigConflictError(
                f"only a draft can be published; {entity_type} '{config_id}' "
                f"v{latest['version']} is {latest['status']}"
            )
        now = _utcnow_iso()
        fields = {
            "status": ConfigStatus.submitted.value,
            "submitted_by": actor,
            "submitted_at": now,
            "updated_at": now,
        }
        self._store.update_config_version(latest["version_id"], fields)
        latest.update(fields)
        self._audit("config.submitted", latest, actor, from_status="draft")
        return ConfigVersion(**latest)

    def approve(self, entity_type: str, config_id: str, actor: str) -> ConfigVersion:
        """Approve + activate a submitted version (RBAC-gated by the caller).

        Records the approval, supersedes the previously active version of the
        same logical configuration, then activates this one. Each transition is
        a separate audit entry.
        """
        self._require_entity(entity_type)
        latest = self._latest(entity_type, config_id)
        if latest is None:
            raise ConfigNotFoundError(
                f"no {entity_type} configuration with id '{config_id}'"
            )
        if latest["status"] != ConfigStatus.submitted.value:
            raise ConfigConflictError(
                f"only a submitted version can be approved; {entity_type} "
                f"'{config_id}' v{latest['version']} is {latest['status']}"
            )

        now = _utcnow_iso()
        # 1) submitted -> approved
        approved_fields = {
            "status": ConfigStatus.approved.value,
            "approved_by": actor,
            "approved_at": now,
            "updated_at": now,
        }
        self._store.update_config_version(latest["version_id"], approved_fields)
        latest.update(approved_fields)
        self._audit("config.approved", latest, actor, from_status="submitted")

        # 2) supersede the currently active version (if any)
        for row in self._store.list_config_versions(entity_type, config_id):
            if (
                row["status"] == ConfigStatus.active.value
                and row["version_id"] != latest["version_id"]
            ):
                superseded_fields = {
                    "status": ConfigStatus.superseded.value,
                    "superseded_by": latest["version_id"],
                    "updated_at": now,
                }
                self._store.update_config_version(row["version_id"], superseded_fields)
                row.update(superseded_fields)
                self._audit(
                    "config.superseded",
                    row,
                    actor,
                    from_status="active",
                    superseded_by=latest["version_id"],
                )

        # 3) approved -> active
        active_fields = {
            "status": ConfigStatus.active.value,
            "activated_at": now,
            "updated_at": now,
        }
        self._store.update_config_version(latest["version_id"], active_fields)
        latest.update(active_fields)
        self._audit("config.activated", latest, actor, from_status="approved")
        return ConfigVersion(**latest)

    # -- integration helpers --------------------------------------------------

    def active_tag_map(self, *, map_id: str = "active-config") -> TagMap:
        """Assemble the active ``tag_mapping`` configs into a live :class:`TagMap`.

        Demonstrates that published configuration feeds ``app.tag_normalization``
        directly: each active tag-mapping version becomes a ``customer_tag ->
        asset_id.metric`` entry (with scale/offset) in the returned map.
        """
        tags: dict[str, dict[str, Any]] = {}
        for row in self._store.list_config_active("tag_mapping"):
            mapping = TagMappingConfig.model_validate(row["payload"])
            tags[mapping.customer_tag] = mapping.to_tag_map_entry()
        return TagMap.from_dict({"tags": tags, "map_id": map_id})
