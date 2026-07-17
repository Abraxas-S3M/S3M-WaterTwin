"""Configuration entity registry: content models + natural keys.

Maps each configuration entity type onto its shared canonical content model (from
:mod:`canonical_water_model`) plus a *natural key* function. The natural key is a
stable, human-meaningful identifier derived from the entity's content (e.g. a tag
mapping's ``customer_tag``); it is used as the default logical ``config_id`` so
two versions describing the same real-world thing share one version history.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from canonical_water_model import CONFIG_ENTITY_MODELS, config_entity_types

#: Natural-key extractors per entity type. Each takes a validated content model
#: and returns the stable logical id for its configuration.
_NATURAL_KEYS: dict[str, Callable[[BaseModel], str]] = {
    "asset": lambda m: m.asset_id,
    "tag_discovery": lambda m: m.customer_tag,
    "tag_mapping": lambda m: m.customer_tag,
    "engineering_unit": lambda m: m.unit,
    "alarm_threshold": lambda m: f"{m.asset_id}.{m.metric}",
    "rated_equipment": lambda m: m.asset_id,
    "pump_curve": lambda m: (f"{m.asset_id}:{m.name}" if m.name else m.asset_id),
    "membrane_model": lambda m: m.model_name,
    "process_stage": lambda m: m.stage_id,
    "sampling_point": lambda m: m.point_id,
    "lab_method": lambda m: m.method_id,
    "compliance_limit": lambda m: (
        f"{m.analyte}:{m.stage.value}" if m.stage else m.analyte
    ),
    "user_role_assignment": lambda m: m.username,
}


def entity_types() -> list[str]:
    """Return the sorted list of supported configuration entity types."""
    return config_entity_types()


def is_known_entity(entity_type: str) -> bool:
    return entity_type in CONFIG_ENTITY_MODELS


def model_for(entity_type: str) -> type[BaseModel]:
    """Return the content model class for ``entity_type``."""
    return CONFIG_ENTITY_MODELS[entity_type]


def natural_key(entity_type: str, model: BaseModel) -> str:
    """Return the natural logical id for a validated content ``model``."""
    return _NATURAL_KEYS[entity_type](model)
