"""EPANET-residual-based leak-localization overlay (preliminary + synthetic).

Turns the hydraulic simulation's pressure-residual leak-localization output into
a geospatial overlay: a GeoJSON ``FeatureCollection`` of candidate *zones*
(polygons) around the suspected nodes, ranked by residual. This **reuses** the
residual ranking produced by ``services/hydraulic-sim`` -- it performs no
independent hydraulics of its own.

Every result is explicitly labelled ``preliminary`` and ``synthetic``: it is an
advisory search-area hint, never a validated leak location.
"""

from __future__ import annotations

from typing import Any, Optional

from .geojson import circle_polygon
from .models import ElementKind, NetworkTopology

#: Base radius (m) of a candidate zone and the extra radius per unit of residual
#: pressure (m). Larger residual -> larger highlighted search area.
ZONE_BASE_RADIUS_M = 40.0
ZONE_RADIUS_PER_RESIDUAL_M = 60.0
ZONE_MAX_RADIUS_M = 400.0

OVERLAY_LABEL = "Preliminary, synthetic leak-localization overlay (advisory only)."


def _zone_radius(residual_m: float) -> float:
    radius = ZONE_BASE_RADIUS_M + max(0.0, residual_m) * ZONE_RADIUS_PER_RESIDUAL_M
    return round(min(radius, ZONE_MAX_RADIUS_M), 2)


def leak_localization_overlay(
    topology: NetworkTopology,
    ranked_candidates: list[tuple[str, float]],
    *,
    suspected_node_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a candidate-zone FeatureCollection from ranked residuals.

    ``ranked_candidates`` is the ``(node_id, residual_pressure_m)`` list from the
    hydraulic simulation's :class:`LeakLocalization`, ordered most-suspected
    first. Each candidate becomes a circular zone whose radius scales with its
    residual and whose ``score`` is the residual normalized against the maximum.
    """
    residuals = [max(0.0, r) for _, r in ranked_candidates]
    max_residual = max(residuals) if residuals else 0.0

    features: list[dict[str, Any]] = []
    for rank, (node_id, residual_m) in enumerate(ranked_candidates, start=1):
        element = topology.by_id(node_id)
        if element is None or element.kind != ElementKind.node:
            continue
        coords = element.geometry.get("coordinates")
        if not coords:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        radius_m = _zone_radius(residual_m)
        score = round(residual_m / max_residual, 4) if max_residual > 0 else 0.0
        features.append(
            {
                "type": "Feature",
                "id": f"leak-zone-{node_id}",
                "geometry": circle_polygon(lon, lat, radius_m),
                "properties": {
                    "kind": "leak_candidate_zone",
                    "node_id": node_id,
                    "canonical_asset_id": element.canonical_asset_id,
                    "rank": rank,
                    "residual_pressure_m": round(float(residual_m), 3),
                    "score": score,
                    "radius_m": radius_m,
                    "suspected": (
                        node_id == suspected_node_id if suspected_node_id else rank == 1
                    ),
                    "center": [round(lon, 7), round(lat, 7)],
                    "status": "preliminary",
                    "provenance": "synthetic",
                },
            }
        )

    fc_metadata: dict[str, Any] = {
        "overlay": "leak_localization",
        "status": "preliminary",
        "provenance": "synthetic",
        "label": OVERLAY_LABEL,
        "engine": "EPANET residual (via hydraulic-sim)",
        "suspected_node_id": suspected_node_id,
        "candidate_count": len(features),
    }
    if metadata:
        fc_metadata.update(metadata)

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": fc_metadata,
    }
