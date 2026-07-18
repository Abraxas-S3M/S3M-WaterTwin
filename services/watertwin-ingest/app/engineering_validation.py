"""Engineering validation for uploaded configuration (poisoned-config defence).

Uploaded configuration bundles (rated equipment, membrane models, pump curves,
alarm thresholds, compliance limits, ...) are validated against the shared
canonical configuration models in
``packages/canonical_water_model/configuration.py``. Those models encode the
physically/engineering-meaningful ranges (e.g. a membrane recovery must be
``0 < r < 1``, an efficiency must be ``0 < e <= 1``, alarm thresholds must be
ordered). A poisoned bundle with out-of-range values is rejected here — long
before any value could reach an advisory calculation — with a clear, itemised
error.

This never widens the safety boundary: configuration is declarative data, never
a control path.
"""

from __future__ import annotations

from typing import Any

from canonical_water_model.configuration import (
    CONFIG_ENTITY_MODELS,
    config_entity_types,
)
from pydantic import ValidationError


class PoisonedConfig(Exception):
    """Raised when uploaded configuration fails engineering validation."""

    def __init__(self, entity_type: str, errors: list[dict[str, Any]]) -> None:
        super().__init__(
            f"configuration entity {entity_type!r} failed engineering validation: "
            f"{len(errors)} error(s)"
        )
        self.entity_type = entity_type
        self.errors = errors


def known_entity_types() -> list[str]:
    """Return the configuration entity types that can be validated."""
    return config_entity_types()


def validate_config_entity(entity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate one configuration entity, returning its normalised dict form.

    Raises :class:`PoisonedConfig` when the payload is out of the engineering-
    valid range (or otherwise malformed), or when ``entity_type`` is unknown.
    """
    model = CONFIG_ENTITY_MODELS.get(entity_type)
    if model is None:
        raise PoisonedConfig(
            entity_type,
            [{"type": "unknown_entity", "msg": f"unknown entity type {entity_type!r}"}],
        )
    try:
        instance = model.model_validate(payload)
    except ValidationError as exc:
        raise PoisonedConfig(entity_type, exc.errors()) from exc
    return instance.model_dump()
