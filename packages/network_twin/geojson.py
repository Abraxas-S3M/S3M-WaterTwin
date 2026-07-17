"""GeoJSON serialization, synthetic geo-referencing, and spatial helpers.

The EPANET model stores an abstract *schematic* layout (small integer x/y
coordinates). To render the twin on a real map and to store it in PostGIS with a
valid SRID, we apply a deterministic **synthetic affine geo-reference**: the
schematic ``(x, y)`` is mapped to WGS84 ``(lon, lat)`` around a configurable
anchor. The result is honest, reproducible, and clearly labelled synthetic -- it
is not a surveyed position.

All geometry emitted here is RFC 7946 GeoJSON (WGS84, lon/lat order).
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Optional

from .models import NetworkElement

#: Synthetic geo-reference defaults. Deliberately generic (a plausible coastal
#: desalination footprint) and overridable via the environment. These are NOT
#: surveyed coordinates -- the twin's positions are synthetic.
DEFAULT_ANCHOR_LON = float(os.environ.get("NETWORK_TWIN_ANCHOR_LON", "55.0"))
DEFAULT_ANCHOR_LAT = float(os.environ.get("NETWORK_TWIN_ANCHOR_LAT", "25.0"))
#: Degrees of longitude/latitude per schematic unit (footprint scale).
DEFAULT_DEG_PER_UNIT = float(os.environ.get("NETWORK_TWIN_DEG_PER_UNIT", "0.002"))


@dataclass(frozen=True)
class GeoReference:
    """A synthetic affine transform from schematic ``(x, y)`` to WGS84 lon/lat."""

    anchor_lon: float = DEFAULT_ANCHOR_LON
    anchor_lat: float = DEFAULT_ANCHOR_LAT
    deg_per_unit: float = DEFAULT_DEG_PER_UNIT
    synthetic: bool = True

    def to_lonlat(self, x: float, y: float) -> list[float]:
        """Map a schematic coordinate to a rounded ``[lon, lat]`` pair."""
        lon = self.anchor_lon + x * self.deg_per_unit
        lat = self.anchor_lat + y * self.deg_per_unit
        return [round(lon, 7), round(lat, 7)]

    def describe(self) -> dict[str, Any]:
        return {
            "anchor_lon": self.anchor_lon,
            "anchor_lat": self.anchor_lat,
            "deg_per_unit": self.deg_per_unit,
            "crs": "EPSG:4326",
            "synthetic": self.synthetic,
            "note": (
                "Coordinates are a synthetic affine geo-reference of the "
                "schematic EPANET layout; they are not surveyed positions."
            ),
        }


def point_geometry(lonlat: list[float]) -> dict[str, Any]:
    return {"type": "Point", "coordinates": list(lonlat)}


def linestring_geometry(coords: list[list[float]]) -> dict[str, Any]:
    return {"type": "LineString", "coordinates": [list(c) for c in coords]}


def feature_collection(
    elements: list[NetworkElement],
    *,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Serialize elements as a GeoJSON ``FeatureCollection``.

    ``metadata`` is attached as a foreign member (allowed by RFC 7946) so callers
    can carry provenance / control-boundary labels alongside the geometry.
    """
    fc: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": [e.to_feature() for e in elements],
    }
    if metadata is not None:
        fc["metadata"] = metadata
    return fc


def _geometry_representative_point(geometry: dict[str, Any]) -> Optional[list[float]]:
    """Return a single representative ``[lon, lat]`` for a geometry.

    Point -> its coordinate; LineString -> its midpoint vertex-wise centroid.
    """
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return None
    if gtype == "Point":
        return [float(coords[0]), float(coords[1])]
    if gtype == "LineString":
        xs = [float(c[0]) for c in coords]
        ys = [float(c[1]) for c in coords]
        return [sum(xs) / len(xs), sum(ys) / len(ys)]
    return None


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    r = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def nearest_elements(
    elements: list[NetworkElement],
    lon: float,
    lat: float,
    *,
    limit: int = 1,
) -> list[dict[str, Any]]:
    """Rank elements by great-circle distance from ``(lon, lat)``.

    Returns a list of ``{"element": NetworkElement, "distance_m": float}`` sorted
    nearest-first, truncated to ``limit``.
    """
    ranked: list[dict[str, Any]] = []
    for e in elements:
        pt = _geometry_representative_point(e.geometry)
        if pt is None:
            continue
        dist = haversine_m(lon, lat, pt[0], pt[1])
        ranked.append({"element": e, "distance_m": round(dist, 3)})
    ranked.sort(key=lambda r: r["distance_m"])
    return ranked[: max(1, limit)]


def circle_polygon(
    center_lon: float,
    center_lat: float,
    radius_m: float,
    *,
    segments: int = 32,
) -> dict[str, Any]:
    """Approximate a geodesic circle as a closed GeoJSON ``Polygon`` ring.

    Used to render leak-localization candidate *zones* around suspect nodes.
    """
    coords: list[list[float]] = []
    lat_rad = math.radians(center_lat)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * max(math.cos(lat_rad), 1e-6)
    for i in range(segments + 1):
        theta = 2 * math.pi * (i / segments)
        dlon = (radius_m * math.cos(theta)) / m_per_deg_lon
        dlat = (radius_m * math.sin(theta)) / m_per_deg_lat
        coords.append([round(center_lon + dlon, 7), round(center_lat + dlat, 7)])
    return {"type": "Polygon", "coordinates": [coords]}
