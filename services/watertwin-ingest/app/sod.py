"""Separation-of-duties rules (enforced server-side).

A proposal that touches asset hierarchy, rated equipment, or alarm thresholds is
*safety-relevant*: the person who submits it may not also approve it. The UI only
reflects these rules; enforcement lives here and in the submit/approve handlers.
"""

from __future__ import annotations

# Configuration entity types considered safety-relevant. These map to the
# Administration workbench panels: asset hierarchy, rated equipment, and alarm
# thresholds.
SAFETY_RELEVANT_ENTITIES: frozenset[str] = frozenset(
    {"asset", "rated_equipment", "alarm_threshold"}
)


def is_safety_relevant(entity: str) -> bool:
    return entity in SAFETY_RELEVANT_ENTITIES


def requires_separate_approver(entities: set[str]) -> bool:
    """True when any touched entity is safety-relevant."""
    return bool(entities & SAFETY_RELEVANT_ENTITIES)


def blocked_entities(entities: set[str]) -> list[str]:
    return sorted(entities & SAFETY_RELEVANT_ENTITIES)
