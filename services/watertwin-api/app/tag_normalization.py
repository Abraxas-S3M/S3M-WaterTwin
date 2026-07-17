"""Tag normalization: map customer OT tags onto the canonical model.

Real OT systems expose data under site-specific *customer tags* (PLC / SCADA
point names, OPC UA NodeIds, Modbus register references, historian point names).
This module maps those tags onto the single canonical
:class:`canonical_water_model.TelemetryReading` model so the rest of the platform
never has to know about a customer's naming or engineering units.

A **tag map** (JSON under ``data/tag-maps/``) declares, per customer tag::

    "<customer_tag>": {
        "asset_id": "AST-HPP-01",   # canonical asset id
        "metric":   "winding_temp_c",
        "unit":     "degC",
        "scale":    1.0,             # canonical = raw * scale + offset
        "offset":   0.0
    }

:func:`normalize` applies ``scale``/``offset``, stamps provenance, and
**validates + rejects** unmapped or invalid (non-numeric / non-finite) tags
rather than silently emitting bad canonical data.

Everything here is **read-only**. Normalization only *reads* raw values and
produces canonical readings; it never writes to any control system.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from canonical_water_model import DataProvenance, TelemetryReading, now_iso

#: Default directory holding tag-map config files (overridable for tests / ops).
_DEFAULT_TAG_MAP_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "tag-maps")
)
TAG_MAP_DIR = os.environ.get("WATERTWIN_TAG_MAP_DIR", _DEFAULT_TAG_MAP_DIR)

_REQUIRED_FIELDS = ("asset_id", "metric", "unit")


class TagMapError(ValueError):
    """Raised when a tag map is structurally invalid."""


@dataclass(frozen=True)
class RawReading:
    """A single raw value read from an OT source, keyed by its customer tag."""

    customer_tag: str
    value: Any
    timestamp: Optional[str] = None
    quality: Optional[str] = None


@dataclass(frozen=True)
class TagMapEntry:
    """Canonical mapping target for one customer tag."""

    asset_id: str
    metric: str
    unit: str
    scale: float = 1.0
    offset: float = 0.0


@dataclass(frozen=True)
class RejectedReading:
    """A raw reading that could not be normalized, with the reason why."""

    customer_tag: str
    value: Any
    reason: str


@dataclass
class NormalizationResult:
    """The outcome of normalizing a batch of raw readings."""

    readings: list[TelemetryReading] = field(default_factory=list)
    rejected: list[RejectedReading] = field(default_factory=list)


def _coerce_float(value: Any, field_name: str, *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise TagMapError(f"{field_name} must be a number, got {value!r}") from exc


class TagMap:
    """An in-memory, validated customer-tag -> canonical-target mapping."""

    def __init__(
        self,
        entries: dict[str, TagMapEntry],
        *,
        map_id: str = "inline",
        description: str = "",
        provenance: DataProvenance = DataProvenance.measured,
        source_path: Optional[str] = None,
    ) -> None:
        self.entries = entries
        self.map_id = map_id
        self.description = description
        self.provenance = provenance
        self.source_path = source_path

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def customer_tags(self) -> list[str]:
        return list(self.entries)

    @classmethod
    def from_dict(
        cls,
        data: dict,
        *,
        map_id: str = "inline",
        source_path: Optional[str] = None,
    ) -> "TagMap":
        """Build (and validate) a tag map from a plain dict.

        Accepts either the wrapped form ``{"tags": {...}, "map_id": ...}`` or a
        bare ``{customer_tag: {...}}`` mapping.
        """
        if not isinstance(data, dict):
            raise TagMapError("tag map must be a JSON object")

        raw_tags = data.get("tags", data)
        if not isinstance(raw_tags, dict) or not raw_tags:
            raise TagMapError("tag map must declare a non-empty 'tags' object")

        provenance_raw = str(data.get("provenance", DataProvenance.measured.value))
        try:
            provenance = DataProvenance(provenance_raw)
        except ValueError as exc:
            raise TagMapError(f"unknown provenance {provenance_raw!r}") from exc

        entries: dict[str, TagMapEntry] = {}
        for tag, spec in raw_tags.items():
            if not isinstance(spec, dict):
                raise TagMapError(f"tag {tag!r} must map to an object")
            missing = [f for f in _REQUIRED_FIELDS if not spec.get(f)]
            if missing:
                raise TagMapError(f"tag {tag!r} is missing required field(s): {missing}")
            entries[str(tag)] = TagMapEntry(
                asset_id=str(spec["asset_id"]),
                metric=str(spec["metric"]),
                unit=str(spec["unit"]),
                scale=_coerce_float(spec.get("scale"), f"{tag}.scale", default=1.0),
                offset=_coerce_float(spec.get("offset"), f"{tag}.offset", default=0.0),
            )

        return cls(
            entries,
            map_id=str(data.get("map_id", map_id)),
            description=str(data.get("description", "")),
            provenance=provenance,
            source_path=source_path,
        )

    @classmethod
    def from_file(cls, path: str) -> "TagMap":
        """Load and validate a tag map from a JSON file path."""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError as exc:
            raise TagMapError(f"tag map not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise TagMapError(f"tag map {path} is not valid JSON: {exc}") from exc
        return cls.from_dict(data, map_id=os.path.basename(path), source_path=path)


def resolve_tag_map_path(name_or_path: str, *, tag_map_dir: str = TAG_MAP_DIR) -> str:
    """Resolve a tag-map reference to a file path.

    A bare name (with or without ``.json``) is looked up under ``tag_map_dir``;
    an absolute or existing relative path is used as-is.
    """
    if os.path.isabs(name_or_path) or os.path.exists(name_or_path):
        return name_or_path
    candidate = name_or_path if name_or_path.endswith(".json") else f"{name_or_path}.json"
    return os.path.join(tag_map_dir, candidate)


def load_tag_map(name_or_path: str, *, tag_map_dir: str = TAG_MAP_DIR) -> TagMap:
    """Load a tag map by bare name (under ``data/tag-maps/``) or by path."""
    return TagMap.from_file(resolve_tag_map_path(name_or_path, tag_map_dir=tag_map_dir))


def normalize(
    raw_readings: Iterable[RawReading],
    tag_map: TagMap,
    *,
    provenance: Optional[DataProvenance] = None,
    default_timestamp: Optional[str] = None,
) -> NormalizationResult:
    """Map raw customer-tag readings onto canonical :class:`TelemetryReading` s.

    Applies ``canonical = raw * scale + offset`` per the tag map. Unmapped tags
    and non-numeric / non-finite values are **rejected** (collected with a
    reason) rather than emitted as canonical readings. This is a pure read
    transform; it never writes anywhere.
    """
    prov = provenance or tag_map.provenance
    ts0 = default_timestamp or now_iso()

    result = NormalizationResult()
    for raw in raw_readings:
        entry = tag_map.entries.get(raw.customer_tag)
        if entry is None:
            result.rejected.append(
                RejectedReading(raw.customer_tag, raw.value, "unmapped tag")
            )
            continue
        try:
            value = float(raw.value)
        except (TypeError, ValueError):
            result.rejected.append(
                RejectedReading(raw.customer_tag, raw.value, "non-numeric value")
            )
            continue
        if not math.isfinite(value):
            result.rejected.append(
                RejectedReading(raw.customer_tag, raw.value, "non-finite value")
            )
            continue
        result.readings.append(
            TelemetryReading(
                asset_id=entry.asset_id,
                metric=entry.metric,
                value=value * entry.scale + entry.offset,
                unit=entry.unit,
                timestamp=raw.timestamp or ts0,
                provenance=prov,
                quality=raw.quality,
            )
        )
    return result
