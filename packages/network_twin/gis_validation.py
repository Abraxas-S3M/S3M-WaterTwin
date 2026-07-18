"""Dependency-light GeoJSON geometry validation.

Geometry is validated **before** it is allowed near PostGIS. Invalid geometry is
*reported* with a reason -- it is never silently repaired, snapped, or dropped.
The checks here are pure Python (no GEOS/shapely dependency) so the shared
``network_twin`` package stays lightweight:

* structural: allowed type, coordinates present, all coordinates finite;
* topological: rings closed, minimum vertex counts, and simple (non
  self-intersecting) polygon rings.

The functions return a :class:`GeometryValidation` describing *why* a geometry is
invalid so the caller can surface it to an operator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

ALLOWED_GEOMETRY_TYPES = frozenset(
    {
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
    }
)


@dataclass(frozen=True)
class GeometryValidation:
    """The result of validating a single GeoJSON geometry."""

    valid: bool
    geometry_type: str | None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "geometry_type": self.geometry_type,
            "reasons": list(self.reasons),
        }


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_position(pos: Any) -> bool:
    return (
        isinstance(pos, list | tuple)
        and len(pos) >= 2
        and _is_finite_number(pos[0])
        and _is_finite_number(pos[1])
    )


def _positions_all_finite(coords: Any) -> bool:
    """Recursively confirm every leaf position in a coordinate array is finite."""
    if _is_position(coords):
        return True
    if isinstance(coords, list | tuple):
        return all(_positions_all_finite(c) for c in coords)
    return False


def _orientation(a: list[float], b: list[float], c: list[float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: list[float], b: list[float], p: list[float]) -> bool:
    return (
        min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    )


def _segments_intersect(
    p1: list[float], p2: list[float], p3: list[float], p4: list[float]
) -> bool:
    """Return True if segment p1p2 properly crosses or overlaps segment p3p4."""
    d1 = _orientation(p3, p4, p1)
    d2 = _orientation(p3, p4, p2)
    d3 = _orientation(p1, p2, p3)
    d4 = _orientation(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True
    if d1 == 0 and _on_segment(p3, p4, p1):
        return True
    if d2 == 0 and _on_segment(p3, p4, p2):
        return True
    if d3 == 0 and _on_segment(p1, p2, p3):
        return True
    if d4 == 0 and _on_segment(p1, p2, p4):  # noqa: SIM103 - clarity over collapse
        return True
    return False


def _ring_self_intersects(ring: list[list[float]]) -> bool:
    """True if a closed ring has any non-adjacent edges that intersect."""
    n = len(ring) - 1  # last vertex repeats the first
    if n < 3:
        return False
    for i in range(n):
        a1, a2 = ring[i], ring[i + 1]
        for j in range(i + 1, n):
            # Skip edges that share a vertex (adjacent, incl. the wrap-around).
            if j == i or j == i + 1 or (i == 0 and j == n - 1):
                continue
            b1, b2 = ring[j], ring[j + 1]
            if _segments_intersect(a1, a2, b1, b2):
                return True
    return False


def _validate_linestring(coords: Any, reasons: list[str]) -> None:
    if not isinstance(coords, list | tuple) or len(coords) < 2:
        reasons.append("linestring must have at least 2 positions")
        return
    if not all(_is_position(p) for p in coords):
        reasons.append("linestring has a non-finite or malformed position")
        return
    distinct = {(round(p[0], 12), round(p[1], 12)) for p in coords}
    if len(distinct) < 2:
        reasons.append("linestring collapses to a single point")


def _validate_ring(ring: Any, reasons: list[str], *, index: int) -> None:
    if not isinstance(ring, list | tuple) or len(ring) < 4:
        reasons.append(f"polygon ring {index} must have at least 4 positions")
        return
    if not all(_is_position(p) for p in ring):
        reasons.append(f"polygon ring {index} has a non-finite or malformed position")
        return
    if list(ring[0][:2]) != list(ring[-1][:2]):
        reasons.append(f"polygon ring {index} is not closed")
        return
    if _ring_self_intersects([list(p) for p in ring]):
        reasons.append(f"polygon ring {index} is self-intersecting")


def _validate_polygon(coords: Any, reasons: list[str]) -> None:
    if not isinstance(coords, list | tuple) or not coords:
        reasons.append("polygon must have at least one ring")
        return
    for i, ring in enumerate(coords):
        _validate_ring(ring, reasons, index=i)


def validate_geometry(geometry: Any) -> GeometryValidation:
    """Validate a GeoJSON geometry object; report (never repair) invalidity."""
    if not isinstance(geometry, dict):
        return GeometryValidation(False, None, ["geometry is not an object"])

    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    reasons: list[str] = []

    if gtype not in ALLOWED_GEOMETRY_TYPES:
        return GeometryValidation(False, gtype if isinstance(gtype, str) else None,
                                  [f"unsupported geometry type: {gtype!r}"])
    if coords is None:
        return GeometryValidation(False, gtype, ["geometry has no coordinates"])
    if not _positions_all_finite(coords):
        return GeometryValidation(False, gtype, ["geometry has non-finite coordinates"])

    if gtype == "Point":
        if not _is_position(coords):
            reasons.append("point must be a single finite position")
    elif gtype == "MultiPoint":
        if not isinstance(coords, list | tuple) or not coords:
            reasons.append("multipoint must have at least one position")
        elif not all(_is_position(p) for p in coords):
            reasons.append("multipoint has a malformed position")
    elif gtype == "LineString":
        _validate_linestring(coords, reasons)
    elif gtype == "MultiLineString":
        if not isinstance(coords, list | tuple) or not coords:
            reasons.append("multilinestring must have at least one line")
        else:
            for line in coords:
                _validate_linestring(line, reasons)
    elif gtype == "Polygon":
        _validate_polygon(coords, reasons)
    elif gtype == "MultiPolygon":
        if not isinstance(coords, list | tuple) or not coords:
            reasons.append("multipolygon must have at least one polygon")
        else:
            for polygon in coords:
                _validate_polygon(polygon, reasons)

    return GeometryValidation(not reasons, gtype, reasons)
