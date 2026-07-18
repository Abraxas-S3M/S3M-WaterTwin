"""Geospatial network-twin package (shared).

A dependency-light geospatial digital twin of the water-distribution network.
It imports its topology from the same EPANET ``.inp`` model that
``services/hydraulic-sim`` runs (so twin and simulation share topology),
geo-references the schematic layout synthetically, links every element to a
canonical ``asset_id``, and serializes to RFC 7946 GeoJSON.

Nothing here writes to any control system; all coordinates are synthetic and all
overlays are preliminary/advisory.
"""

from __future__ import annotations

from .epanet_import import (
    BUNDLED_INP,
    CANONICAL_ASSET_LINKS,
    HYDRAULIC_SIM_INP,
    import_network,
    parse_inp,
    resolve_inp_path,
)
from .geojson import (
    GeoReference,
    circle_polygon,
    feature_collection,
    haversine_m,
    nearest_elements,
)
from .gis_validation import (
    ALLOWED_GEOMETRY_TYPES,
    GeometryValidation,
    validate_geometry,
)
from .models import (
    ElementKind,
    NetworkElement,
    NetworkElementType,
    NetworkTopology,
    LINK_TYPES,
    NODE_TYPES,
)
from .overlay import OVERLAY_LABEL, leak_localization_overlay

__all__ = [
    "BUNDLED_INP",
    "HYDRAULIC_SIM_INP",
    "CANONICAL_ASSET_LINKS",
    "import_network",
    "parse_inp",
    "resolve_inp_path",
    "GeoReference",
    "feature_collection",
    "nearest_elements",
    "haversine_m",
    "circle_polygon",
    "ElementKind",
    "NetworkElement",
    "NetworkElementType",
    "NetworkTopology",
    "NODE_TYPES",
    "LINK_TYPES",
    "leak_localization_overlay",
    "OVERLAY_LABEL",
    "validate_geometry",
    "GeometryValidation",
    "ALLOWED_GEOMETRY_TYPES",
]
