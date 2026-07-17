"""Import a geospatial network twin from the canonical EPANET ``.inp`` model.

The twin and ``services/hydraulic-sim`` **share topology**: both are driven by
the same EPANET input file (``ro-handoff.inp``). This module contains a focused,
dependency-light parser for the EPANET sections the twin needs (nodes, links,
coordinates, vertices) so ``watertwin-api`` can build the twin without pulling in
the heavy EPANET/WNTR runtime. A parity test cross-checks this parser against
WNTR's own parse of the same file.

The parsed schematic layout is geo-referenced (synthetically) and each element is
linked to a canonical ``asset_id`` (see :data:`CANONICAL_ASSET_LINKS`).
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .geojson import GeoReference, linestring_geometry, point_geometry
from .models import (
    ElementKind,
    NetworkElement,
    NetworkElementType,
    NetworkTopology,
)

#: Bundled canonical network (a copy of ``services/hydraulic-sim/models``). Both
#: services receive ``packages/`` in their image, so the twin can always reach a
#: topology-identical model; a drift test guards the two files against divergence.
BUNDLED_INP = os.path.join(os.path.dirname(__file__), "networks", "ro-handoff.inp")

#: Path to the model the hydraulic simulation uses, when running from the repo.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HYDRAULIC_SIM_INP = os.path.join(
    _REPO_ROOT, "services", "hydraulic-sim", "models", "ro-handoff.inp"
)

#: Mapping from EPANET element id to a *pre-existing* canonical platform asset id.
#: The hydraulic model is the product-water handoff subsystem; the two parallel
#: product-transfer pumps belong to the canonical booster/permeate pumping asset
#: class. Elements without an entry here are their own canonical asset. This map
#: is advisory and intentionally explicit so the linkage is auditable.
CANONICAL_ASSET_LINKS: dict[str, str] = {
    "PU-PROD-1": "AST-BOOST-01",
    "PU-PROD-2": "AST-BOOST-01",
}


def resolve_inp_path(inp_path: Optional[str] = None) -> str:
    """Resolve which ``.inp`` to import.

    Order: explicit argument -> ``NETWORK_TWIN_INP`` env -> the hydraulic-sim
    model in the repo (shared topology) -> the bundled package copy.
    """
    candidates = [
        inp_path,
        os.environ.get("NETWORK_TWIN_INP"),
        HYDRAULIC_SIM_INP,
        BUNDLED_INP,
    ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            return cand
    return BUNDLED_INP


def _iter_sections(text: str):
    """Yield ``(section_name, [row_tokens, ...])`` for an EPANET ``.inp``."""
    section: Optional[str] = None
    rows: list[list[str]] = []
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            if section is not None:
                yield section, rows
            section = line[1:-1].strip().upper()
            rows = []
            continue
        if section is None:
            continue
        rows.append(line.split())
    if section is not None:
        yield section, rows


def parse_inp(inp_path: Optional[str] = None) -> dict[str, Any]:
    """Parse the EPANET ``.inp`` into a plain topology dict.

    Returns nodes (with type, elevation/head, coordinates) and links (with type,
    endpoints, attributes, polyline vertices).
    """
    path = resolve_inp_path(inp_path)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    nodes: dict[str, dict[str, Any]] = {}
    links: dict[str, dict[str, Any]] = {}
    coordinates: dict[str, list[float]] = {}
    vertices: dict[str, list[list[float]]] = {}

    for section, rows in _iter_sections(text):
        for tok in rows:
            if section == "JUNCTIONS":
                nodes[tok[0]] = {
                    "type": NetworkElementType.junction,
                    "elevation": _f(tok, 1),
                    "base_demand": _f(tok, 2),
                }
            elif section == "RESERVOIRS":
                nodes[tok[0]] = {"type": NetworkElementType.reservoir, "head": _f(tok, 1)}
            elif section == "TANKS":
                nodes[tok[0]] = {
                    "type": NetworkElementType.tank,
                    "elevation": _f(tok, 1),
                    "init_level": _f(tok, 2),
                    "min_level": _f(tok, 3),
                    "max_level": _f(tok, 4),
                    "diameter": _f(tok, 5),
                }
            elif section == "PIPES":
                links[tok[0]] = {
                    "type": NetworkElementType.pipe,
                    "start_node": tok[1],
                    "end_node": tok[2],
                    "length": _f(tok, 3),
                    "diameter": _f(tok, 4),
                    "roughness": _f(tok, 5),
                    "status": tok[7] if len(tok) > 7 else "Open",
                }
            elif section == "PUMPS":
                links[tok[0]] = {
                    "type": NetworkElementType.pump,
                    "start_node": tok[1],
                    "end_node": tok[2],
                    "properties": " ".join(tok[3:]) if len(tok) > 3 else "",
                }
            elif section == "VALVES":
                links[tok[0]] = {
                    "type": NetworkElementType.valve,
                    "start_node": tok[1],
                    "end_node": tok[2],
                    "diameter": _f(tok, 3),
                    "valve_type": tok[4] if len(tok) > 4 else None,
                    "setting": _f(tok, 5),
                }
            elif section == "COORDINATES":
                coordinates[tok[0]] = [float(tok[1]), float(tok[2])]
            elif section == "VERTICES":
                vertices.setdefault(tok[0], []).append([float(tok[1]), float(tok[2])])

    return {
        "nodes": nodes,
        "links": links,
        "coordinates": coordinates,
        "vertices": vertices,
        "source_path": path,
    }


def _f(tok: list[str], idx: int) -> Optional[float]:
    """Best-effort float extraction from a token list (None when absent)."""
    if idx >= len(tok):
        return None
    try:
        return float(tok[idx])
    except ValueError:
        return None


def _canonical(element_id: str) -> tuple[str, bool]:
    linked = CANONICAL_ASSET_LINKS.get(element_id)
    if linked:
        return linked, True
    return element_id, False


def import_network(
    inp_path: Optional[str] = None,
    *,
    network_id: str = "ro-handoff",
    georef: Optional[GeoReference] = None,
) -> NetworkTopology:
    """Import the EPANET model into a geo-referenced :class:`NetworkTopology`."""
    georef = georef or GeoReference()
    parsed = parse_inp(inp_path)
    coordinates = parsed["coordinates"]
    vertices = parsed["vertices"]

    elements: list[NetworkElement] = []

    for node_id, attrs in parsed["nodes"].items():
        xy = coordinates.get(node_id, [0.0, 0.0])
        lonlat = georef.to_lonlat(xy[0], xy[1])
        canonical_id, linked = _canonical(node_id)
        props = {k: v for k, v in attrs.items() if k != "type" and v is not None}
        props["schematic_xy"] = xy
        elements.append(
            NetworkElement(
                element_id=node_id,
                element_type=attrs["type"],
                kind=ElementKind.node,
                canonical_asset_id=canonical_id,
                canonical_link=linked,
                node_id=node_id,
                geometry=point_geometry(lonlat),
                properties=props,
            )
        )

    for link_id, attrs in parsed["links"].items():
        start = attrs["start_node"]
        end = attrs["end_node"]
        start_xy = coordinates.get(start, [0.0, 0.0])
        end_xy = coordinates.get(end, [0.0, 0.0])
        path_xy = [start_xy, *vertices.get(link_id, []), end_xy]
        line = [georef.to_lonlat(x, y) for x, y in path_xy]
        canonical_id, linked = _canonical(link_id)
        props = {
            k: v
            for k, v in attrs.items()
            if k not in {"type", "start_node", "end_node"} and v is not None
        }
        elements.append(
            NetworkElement(
                element_id=link_id,
                element_type=attrs["type"],
                kind=ElementKind.link,
                canonical_asset_id=canonical_id,
                canonical_link=linked,
                start_node=start,
                end_node=end,
                geometry=linestring_geometry(line),
                properties=props,
            )
        )

    metadata = {
        "network_id": network_id,
        "source_path": parsed["source_path"],
        "element_count": len(elements),
        "node_count": len(parsed["nodes"]),
        "link_count": len(parsed["links"]),
        "engine": "EPANET (shared with hydraulic-sim)",
        "geo_reference": georef.describe(),
        "provenance": "synthetic",
    }
    return NetworkTopology(network_id=network_id, elements=elements, metadata=metadata)
