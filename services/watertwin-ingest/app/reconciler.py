"""Reconcile a :class:`ParseResult` against the current canonical configuration.

The canonical configuration is fetched from ``watertwin-api`` **over HTTP**
(never read from a database by this service). Each parsed entity is matched to a
canonical record:

* **exact** match on ``asset_id`` (the entity id), else
* **fuzzy** match on ``name`` with a ``match_confidence`` in ``[0, 1]``; below a
  configurable threshold the entity is proposed as **new** rather than matched.

For a matched entity every parsed (customer-supplied) field is classified as
``unchanged``, ``changed`` (a conflict), or ``new``. A conflict is **never**
auto-resolved — it is surfaced for a human to decide.

Nothing here writes to the canonical model or to any control system: it only
reads the canonical config and returns an advisory diff.
"""

from __future__ import annotations

import math
from difflib import SequenceMatcher
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .parsers import ParseResult

#: Network element types that map onto the canonical network configuration. Other
#: parsed types (e.g. curves, patterns) are carried in the ParseResult but are
#: not reconciled against the canonical network model in this phase.
DEFAULT_RECONCILED_TYPES: frozenset[str] = frozenset(
    {"junction", "reservoir", "tank", "pipe", "pump", "valve"}
)

_META_KEYS = frozenset(
    {
        "element_id",
        "element_type",
        "kind",
        "canonical_asset_id",
        "canonical_link",
        "node_id",
        "schematic_xy",
    }
)


class CanonicalConfigError(RuntimeError):
    """Raised when the canonical configuration cannot be fetched."""


class CanonicalRecord(BaseModel):
    """One current canonical record to reconcile a parsed entity against."""

    record_id: str
    name: str
    entity_type: str
    fields: dict[str, Any] = Field(default_factory=dict)


class MatchType(str, Enum):
    """How a parsed entity was matched to a canonical record."""

    exact = "exact"
    fuzzy = "fuzzy"
    none = "none"


class FieldClassification(str, Enum):
    """The reconciliation class of a single field."""

    unchanged = "unchanged"
    changed = "changed"
    new = "new"


class FieldDiff(BaseModel):
    """The reconciliation of one parsed field against the canonical record."""

    field: str
    classification: FieldClassification
    current_value: Any = None
    proposed_value: Any = None


class ReconciledEntity(BaseModel):
    """A parsed entity reconciled against the canonical configuration."""

    entity_type: str
    parsed_entity_id: str
    name: str | None = None
    matched_record_id: str | None = None
    match_type: MatchType
    match_confidence: float
    is_new: bool
    conflict: bool
    source_line: int
    field_diffs: list[FieldDiff] = Field(default_factory=list)


class ReconcileResult(BaseModel):
    """The advisory diff of a whole :class:`ParseResult` against canonical config."""

    entities: list[ReconciledEntity] = Field(default_factory=list)
    skipped_types: dict[str, int] = Field(default_factory=dict)
    matched_count: int = 0
    new_count: int = 0
    conflict_count: int = 0


def _values_equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-9)
    return a == b


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


class CanonicalConfigClient:
    """Fetch the current canonical network configuration from watertwin-api.

    Accepts any session exposing ``.get(path)`` returning an object with
    ``.status_code`` and ``.json()`` — satisfied by both ``httpx.Client`` (real
    deployment) and Starlette's ``TestClient`` / a fake session (tests). This is
    the same injectable-session pattern used by ``watertwin-api``'s hydraulic
    client, and keeps the ingest service database-free.
    """

    FEATURES_PATH = "/api/v1/network/features"

    def __init__(
        self,
        base_url: str | None = None,
        session: Any = None,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        if session is None:
            import httpx

            headers = {"Authorization": f"Bearer {token}"} if token else None
            session = httpx.Client(base_url=base_url, timeout=timeout, headers=headers)
        self._session = session

    def fetch_records(self) -> list[CanonicalRecord]:
        """Fetch and adapt the canonical network into :class:`CanonicalRecord`s."""
        try:
            resp = self._session.get(self.FEATURES_PATH)
        except Exception as exc:
            raise CanonicalConfigError(
                f"could not reach watertwin-api canonical config: {exc}"
            ) from exc
        if resp.status_code != 200:
            raise CanonicalConfigError(
                f"canonical config fetch failed: HTTP {resp.status_code}"
            )
        collection = resp.json()
        records: list[CanonicalRecord] = []
        for feature in collection.get("features", []):
            record = _feature_to_record(feature)
            if record is not None:
                records.append(record)
        return records


def _feature_to_record(feature: dict[str, Any]) -> CanonicalRecord | None:
    props = feature.get("properties") or {}
    element_id = props.get("element_id") or feature.get("id")
    element_type = props.get("element_type")
    if not element_id or not element_type:
        return None
    fields = _adapt_fields(element_type, props)
    return CanonicalRecord(
        record_id=str(element_id),
        name=str(element_id),
        entity_type=str(element_type),
        fields=fields,
    )


def _adapt_fields(element_type: str, props: dict[str, Any]) -> dict[str, Any]:
    """Map network-twin feature properties onto normalized canonical field names.

    Keys that are already normalized (e.g. ``elevation_m``) pass through
    unchanged; known raw keys are renamed to the canonical field names the
    parser emits so like is compared with like.
    """
    rename = {
        "elevation": "elevation_m",
        "base_demand": "base_demand_m3h",
        "head": "head_m",
        "init_level": "init_level_m",
        "min_level": "min_level_m",
        "max_level": "max_level_m",
        "length": "length_m",
        "min_volume": "min_volume_m3",
        "start_node": "node1",
        "end_node": "node2",
    }
    if element_type == "tank":
        rename["diameter"] = "diameter_m"
    elif element_type in {"pipe", "valve"}:
        rename["diameter"] = "diameter_mm"
    fields: dict[str, Any] = {}
    for key, value in props.items():
        if key in _META_KEYS or value is None:
            continue
        fields[rename.get(key, key)] = value
    return fields


def reconcile(
    parse_result: ParseResult,
    canonical_records: list[CanonicalRecord],
    *,
    match_threshold: float,
    reconciled_types: frozenset[str] = DEFAULT_RECONCILED_TYPES,
) -> ReconcileResult:
    """Diff ``parse_result`` against ``canonical_records`` (see module docstring)."""
    by_id: dict[str, CanonicalRecord] = {r.record_id: r for r in canonical_records}
    by_type: dict[str, list[CanonicalRecord]] = {}
    for record in canonical_records:
        by_type.setdefault(record.entity_type, []).append(record)

    result = ReconcileResult()
    for entity in parse_result.entities:
        if entity.entity_type not in reconciled_types:
            result.skipped_types[entity.entity_type] = (
                result.skipped_types.get(entity.entity_type, 0) + 1
            )
            continue

        match = by_id.get(entity.entity_id)
        if match is not None and match.entity_type == entity.entity_type:
            reconciled = _reconcile_matched(entity, match, MatchType.exact, 1.0)
        else:
            reconciled = _reconcile_fuzzy(entity, by_type, match_threshold)

        if reconciled.is_new:
            result.new_count += 1
        else:
            result.matched_count += 1
        if reconciled.conflict:
            result.conflict_count += 1
        result.entities.append(reconciled)
    return result


def _reconcile_fuzzy(
    entity: Any,
    by_type: dict[str, list[CanonicalRecord]],
    match_threshold: float,
) -> ReconciledEntity:
    candidates = by_type.get(entity.entity_type, [])
    best: CanonicalRecord | None = None
    best_score = 0.0
    entity_name = entity.name or entity.entity_id
    for candidate in candidates:
        score = _name_similarity(entity_name, candidate.name)
        if score > best_score:
            best_score = score
            best = candidate
    if best is not None and best_score >= match_threshold:
        return _reconcile_matched(entity, best, MatchType.fuzzy, best_score)
    return _reconcile_new(entity, best_score)


def _reconcile_matched(
    entity: Any,
    record: CanonicalRecord,
    match_type: MatchType,
    confidence: float,
) -> ReconciledEntity:
    diffs: list[FieldDiff] = []
    conflict = False
    for field, proposed in entity.fields.items():
        if field in record.fields:
            current = record.fields[field]
            if _values_equal(current, proposed):
                classification = FieldClassification.unchanged
            else:
                classification = FieldClassification.changed
                conflict = True
            diffs.append(
                FieldDiff(
                    field=field,
                    classification=classification,
                    current_value=current,
                    proposed_value=proposed,
                )
            )
        else:
            diffs.append(
                FieldDiff(
                    field=field,
                    classification=FieldClassification.new,
                    current_value=None,
                    proposed_value=proposed,
                )
            )
    return ReconciledEntity(
        entity_type=entity.entity_type,
        parsed_entity_id=entity.entity_id,
        name=entity.name,
        matched_record_id=record.record_id,
        match_type=match_type,
        match_confidence=round(confidence, 4),
        is_new=False,
        conflict=conflict,
        source_line=entity.source_line,
        field_diffs=diffs,
    )


def _reconcile_new(entity: Any, best_score: float) -> ReconciledEntity:
    diffs = [
        FieldDiff(
            field=field,
            classification=FieldClassification.new,
            current_value=None,
            proposed_value=proposed,
        )
        for field, proposed in entity.fields.items()
    ]
    return ReconciledEntity(
        entity_type=entity.entity_type,
        parsed_entity_id=entity.entity_id,
        name=entity.name,
        matched_record_id=None,
        match_type=MatchType.none,
        match_confidence=round(best_score, 4),
        is_new=True,
        conflict=False,
        source_line=entity.source_line,
        field_diffs=diffs,
    )
