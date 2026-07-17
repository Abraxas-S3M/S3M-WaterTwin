"""REST API for the versioned, approval-gated configuration store.

Mounted under ``/api/v1/config``. Reads require any authenticated role; authoring
actions (create/update/publish) require the ``engineer`` role; approval requires
``engineer`` or ``admin`` (``admin`` is always accepted). There is deliberately
**no delete** endpoint for published versions -- a change supersedes the prior
active version instead.

Every response carries the read-only :class:`ControlBoundary`: configuration is
declarative and never touches a control path, so the advisory invariant is
unchanged.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from canonical_water_model import ControlBoundary

from ..auth import Principal, get_current_user, require_role
from .models import ConfigCreateRequest, ConfigUpdateRequest
from .service import ConfigError, ConfigService

router = APIRouter(prefix="/api/v1/config", tags=["configuration"])

_service: Optional[ConfigService] = None


def configure(service: ConfigService) -> None:
    """Bind the module-level service (called once from ``app.main``)."""
    global _service
    _service = service


def get_config_service() -> ConfigService:
    if _service is None:  # pragma: no cover - defensive; always configured at startup
        raise HTTPException(status_code=503, detail="configuration service not initialized")
    return _service


def _handle(exc: ConfigError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _envelope(payload: dict) -> dict:
    return {**payload, "control_boundary": ControlBoundary().model_dump()}


# --- reads (any authenticated role) ----------------------------------------


@router.get("/entities", dependencies=[Depends(get_current_user)])
def list_entities(service: ConfigService = Depends(get_config_service)) -> dict:
    """List the supported configuration entity types."""
    return _envelope({"entities": service.entity_types()})


@router.get("/{entity}", dependencies=[Depends(get_current_user)])
def list_active(
    entity: str, service: ConfigService = Depends(get_config_service)
) -> dict:
    """List the active version of every configuration of ``entity``."""
    try:
        items = service.list_active(entity)
    except ConfigError as exc:
        raise _handle(exc)
    return _envelope({"entity": entity, "items": [i.model_dump(mode="json") for i in items]})


@router.get("/{entity}/{config_id}", dependencies=[Depends(get_current_user)])
def get_active(
    entity: str, config_id: str, service: ConfigService = Depends(get_config_service)
) -> dict:
    """Return the active (or latest) version of one configuration."""
    try:
        version = service.get_active(entity, config_id)
    except ConfigError as exc:
        raise _handle(exc)
    return _envelope(version.model_dump(mode="json"))


@router.get("/{entity}/{config_id}/versions", dependencies=[Depends(get_current_user)])
def list_versions(
    entity: str, config_id: str, service: ConfigService = Depends(get_config_service)
) -> dict:
    """List every version of one logical configuration, oldest-first."""
    try:
        versions = service.list_versions(entity, config_id)
    except ConfigError as exc:
        raise _handle(exc)
    return _envelope(
        {
            "entity": entity,
            "config_id": config_id,
            "versions": [v.model_dump(mode="json") for v in versions],
        }
    )


# --- authoring (engineer role) ---------------------------------------------


@router.post("/{entity}")
def create_config(
    entity: str,
    body: ConfigCreateRequest,
    user: Principal = Depends(require_role("engineer")),
    service: ConfigService = Depends(get_config_service),
) -> dict:
    """Create a new draft version of a configuration entity."""
    try:
        version = service.create(entity, body.payload, actor=user.actor, config_id=body.config_id)
    except ConfigError as exc:
        raise _handle(exc)
    return _envelope(version.model_dump(mode="json"))


@router.put("/{entity}/{config_id}")
def update_config(
    entity: str,
    config_id: str,
    body: ConfigUpdateRequest,
    user: Principal = Depends(require_role("engineer")),
    service: ConfigService = Depends(get_config_service),
) -> dict:
    """Replace the payload of the current draft version (immutable-on-publish)."""
    try:
        version = service.update(entity, config_id, body.payload, actor=user.actor)
    except ConfigError as exc:
        raise _handle(exc)
    return _envelope(version.model_dump(mode="json"))


@router.post("/{entity}/{config_id}/publish")
def publish_config(
    entity: str,
    config_id: str,
    user: Principal = Depends(require_role("engineer")),
    service: ConfigService = Depends(get_config_service),
) -> dict:
    """Submit the current draft for approval (draft -> submitted)."""
    try:
        version = service.publish(entity, config_id, actor=user.actor)
    except ConfigError as exc:
        raise _handle(exc)
    return _envelope(version.model_dump(mode="json"))


# --- approval (engineer/admin only) ----------------------------------------


@router.post("/{entity}/{config_id}/approve")
def approve_config(
    entity: str,
    config_id: str,
    user: Principal = Depends(require_role("engineer")),
    service: ConfigService = Depends(get_config_service),
) -> dict:
    """Approve + activate a submitted version, superseding the prior active one.

    RBAC: only an ``engineer`` or ``admin`` may approve (``admin`` is always
    accepted). This records the approval and activation in the audit chain and
    never writes to any control system.
    """
    try:
        version = service.approve(entity, config_id, actor=user.actor)
    except ConfigError as exc:
        raise _handle(exc)
    return _envelope(version.model_dump(mode="json"))
