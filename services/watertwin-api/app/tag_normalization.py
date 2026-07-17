"""Tag normalization -- compatibility shim.

The tag-normalization layer and the tag-map schema were moved to the shared,
importable :mod:`ot_ingestion.tag_normalization` package so both this API and the
independently deployable ``services/edge-gateway`` reuse a single implementation
(no duplicated logic). This module re-exports that package unchanged so the
existing ``app.tag_normalization`` import path (and its behaviour) is preserved.
"""

from __future__ import annotations

from ot_ingestion.tag_normalization import (  # noqa: F401
    TAG_MAP_DIR,
    NormalizationResult,
    RawReading,
    RejectedReading,
    TagMap,
    TagMapEntry,
    TagMapError,
    load_tag_map,
    normalize,
    resolve_tag_map_path,
)

__all__ = [
    "TAG_MAP_DIR",
    "NormalizationResult",
    "RawReading",
    "RejectedReading",
    "TagMap",
    "TagMapEntry",
    "TagMapError",
    "load_tag_map",
    "normalize",
    "resolve_tag_map_path",
]
