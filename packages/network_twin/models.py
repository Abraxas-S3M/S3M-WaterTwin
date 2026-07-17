"""Canonical models for the geospatial network twin.

These Pydantic v2 models describe a water-distribution network as a set of
geo-referenced *elements* (nodes and links) carrying GeoJSON geometry and a link
back to a canonical ``asset_id``. They are shared across services so the
geospatial twin and the hydraulic simulation reason about the same topology.

Everything the twin surfaces is **advisory / synthetic**: the geographic
coordinates are produced by a synthetic affine geo-reference of the schematic
EPANET layout (see :mod:`network_twin.geojson`) and are never surveyed
positions. Geometry is emitted as RFC 7946 GeoJSON (WGS84 lon/lat).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ElementKind(str, Enum):
    """Whether a network element is a node (point) or a link (line)."""

    node = "node"
    link = "link"


class NetworkElementType(str, Enum):
    """The EPANET element classes modelled by the twin."""

    junction = "junction"
    reservoir = "reservoir"
    tank = "tank"
    pipe = "pipe"
    pump = "pump"
    valve = "valve"


#: EPANET element types that are nodes (points) vs links (lines).
NODE_TYPES = frozenset(
    {NetworkElementType.junction, NetworkElementType.reservoir, NetworkElementType.tank}
)
LINK_TYPES = frozenset(
    {NetworkElementType.pipe, NetworkElementType.pump, NetworkElementType.valve}
)


class NetworkElement(BaseModel):
    """A single geo-referenced network element linked to a canonical asset.

    ``element_id`` is the EPANET id (e.g. ``"PU-PROD-1"``). ``canonical_asset_id``
    is the platform asset it maps to; when no pre-existing canonical asset applies
    the element is its own canonical asset (``canonical_asset_id == element_id``
    and ``canonical_link`` is ``False``). ``geometry`` is a GeoJSON geometry
    object (``Point`` for nodes, ``LineString`` for links). ``properties`` carries
    the hydraulic attributes (elevation, diameter, length, ...).
    """

    element_id: str
    element_type: NetworkElementType
    kind: ElementKind
    canonical_asset_id: str
    canonical_link: bool = False
    #: For nodes: the node id (== element_id). For links: None.
    node_id: Optional[str] = None
    #: For links: the endpoint node ids. For nodes: None.
    start_node: Optional[str] = None
    end_node: Optional[str] = None
    geometry: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)

    def to_feature(self) -> dict[str, Any]:
        """Serialize this element as an RFC 7946 GeoJSON Feature."""
        return {
            "type": "Feature",
            "id": self.element_id,
            "geometry": self.geometry,
            "properties": {
                "element_id": self.element_id,
                "element_type": self.element_type.value,
                "kind": self.kind.value,
                "canonical_asset_id": self.canonical_asset_id,
                "canonical_link": self.canonical_link,
                "node_id": self.node_id,
                "start_node": self.start_node,
                "end_node": self.end_node,
                **self.properties,
            },
        }


class NetworkTopology(BaseModel):
    """A parsed, geo-referenced network: an ordered set of elements + metadata."""

    network_id: str = "ro-handoff"
    elements: list[NetworkElement] = Field(default_factory=list)
    #: Provenance/geo-reference metadata surfaced alongside every response.
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def nodes(self) -> list[NetworkElement]:
        return [e for e in self.elements if e.kind == ElementKind.node]

    @property
    def links(self) -> list[NetworkElement]:
        return [e for e in self.elements if e.kind == ElementKind.link]

    def by_id(self, element_id: str) -> Optional[NetworkElement]:
        for e in self.elements:
            if e.element_id == element_id:
                return e
        return None

    def by_asset(self, asset_id: str) -> list[NetworkElement]:
        """Return elements linked to ``asset_id`` (canonical id or element id)."""
        return [
            e
            for e in self.elements
            if e.canonical_asset_id == asset_id or e.element_id == asset_id
        ]
