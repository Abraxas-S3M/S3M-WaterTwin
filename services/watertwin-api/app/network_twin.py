"""Geospatial network-twin service layer for watertwin-api.

Builds the network twin from the shared EPANET model (topology-identical to
``services/hydraulic-sim``), loads it into the PostGIS-backed
:class:`~app.network_store.NetworkStore` (in-memory fallback), and answers the
``/api/v1/network/`` reads: GeoJSON feature collections, per-asset spatial
lookup, nearest-element lookup, and the EPANET-residual leak-localization
overlay.

Everything is advisory and read-only: coordinates are synthetic, overlays are
preliminary, and the control boundary is attached to every response.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from canonical_water_model import ControlBoundary
from network_twin import (
    NetworkTopology,
    import_network,
    leak_localization_overlay,
)
from simulation_contracts import SimulationResult

from .network_store import NetworkStore

NETWORK_ID = os.environ.get("NETWORK_TWIN_ID", "ro-handoff")


def build_topology() -> NetworkTopology:
    """Import the twin topology from the shared EPANET model."""
    return import_network(network_id=NETWORK_ID)


class NetworkTwin:
    """Coordinates the imported topology and its spatial store."""

    def __init__(self, store: NetworkStore, topology: Optional[NetworkTopology] = None) -> None:
        self.store = store
        self.topology = topology or build_topology()

    def ensure_loaded(self) -> int:
        """Load the topology into the store if it is empty. Returns element count."""
        if self.store.count() == 0:
            return self.store.load_elements(self.topology.elements)
        return self.store.count()

    def reload(self) -> int:
        """Re-import and reload the topology (e.g. after an ``.inp`` change)."""
        self.topology = build_topology()
        return self.store.load_elements(self.topology.elements)

    def _metadata(self, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        meta = {
            **self.topology.metadata,
            "storage": self.store.describe(),
            "control_boundary": ControlBoundary().model_dump(),
        }
        if extra:
            meta.update(extra)
        return meta

    def feature_collection(
        self,
        *,
        element_type: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> dict[str, Any]:
        self.ensure_loaded()
        return self.store.features(
            element_type=element_type,
            kind=kind,
            metadata=self._metadata(
                {"filter": {"element_type": element_type, "kind": kind}}
            ),
        )

    def asset_features(self, asset_id: str) -> dict[str, Any]:
        self.ensure_loaded()
        elements = self.store.by_asset(asset_id)
        from network_twin import feature_collection as _fc

        return _fc(
            elements,
            metadata=self._metadata(
                {"asset_id": asset_id, "match_count": len(elements)}
            ),
        )

    def nearest(self, lon: float, lat: float, *, limit: int = 1) -> dict[str, Any]:
        self.ensure_loaded()
        ranked = self.store.nearest(lon, lat, limit=limit)
        return {
            "query": {"lon": lon, "lat": lat, "limit": limit},
            "results": [
                {
                    "distance_m": r["distance_m"],
                    "feature": r["element"].to_feature(),
                }
                for r in ranked
            ],
            "metadata": self._metadata(),
        }

    def leak_overlay(self, result: SimulationResult) -> dict[str, Any]:
        """Build the leak-localization overlay from a hydraulic result.

        Reuses the EPANET pressure-residual ranking in
        ``result.outputs.leak_localization`` -- no independent hydraulics.
        """
        self.ensure_loaded()
        localization = result.outputs.leak_localization
        ranked = list(localization.ranked_candidates) if localization else []
        suspected = localization.suspected_node_id if localization else None
        overlay = leak_localization_overlay(
            self.topology,
            [(str(n), float(r)) for n, r in ranked],
            suspected_node_id=suspected,
            metadata={
                "simulation_id": result.simulation_id,
                "scenario": result.scenario.value,
                "network_id": result.network_id,
                "control_boundary": ControlBoundary().model_dump(),
            },
        )
        return overlay
