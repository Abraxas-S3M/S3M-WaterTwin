"""Package-level tests for the shared geospatial network twin.

Exercises the twin importer, GeoJSON serialization, spatial helpers, and the
leak-localization overlay builder without any service dependency. The
EPANET-parity check against WNTR is skipped when WNTR is not installed (the
packages CI job runs without it; the watertwin-api job runs the full parity).
"""

from __future__ import annotations

import filecmp

import pytest

import network_twin as nt
from network_twin import epanet_import


EXPECTED = {
    "junction": {"J-PS", "J-PD", "J-HANDOFF", "J-D1", "J-D2", "J-D3"},
    "reservoir": {"R-PERM"},
    "tank": {"T-PROD"},
    "pipe": {"P-SUCT", "P-TANK", "P-MAIN", "P-D12", "P-D13"},
    "pump": {"PU-PROD-1", "PU-PROD-2"},
    "valve": {"CV-HANDOFF"},
}


def _by_type(topo, element_type: str) -> set[str]:
    return {e.element_id for e in topo.elements if e.element_type.value == element_type}


def test_import_topology_counts_and_ids():
    topo = nt.import_network()
    for element_type, ids in EXPECTED.items():
        assert _by_type(topo, element_type) == ids
    assert len(topo.nodes) == 8
    assert len(topo.links) == 8


def test_bundled_model_shares_topology_with_hydraulic_sim():
    assert filecmp.cmp(
        epanet_import.BUNDLED_INP, epanet_import.HYDRAULIC_SIM_INP, shallow=False
    )


def test_parity_with_wntr():
    wntr = pytest.importorskip("wntr")
    wn = wntr.network.WaterNetworkModel(epanet_import.HYDRAULIC_SIM_INP)
    topo = nt.import_network()
    assert _by_type(topo, "junction") == set(wn.junction_name_list)
    assert _by_type(topo, "pipe") == set(wn.pipe_name_list)
    assert _by_type(topo, "pump") == set(wn.pump_name_list)
    assert _by_type(topo, "valve") == set(wn.valve_name_list)
    for link_name in wn.link_name_list:
        link = wn.get_link(link_name)
        element = topo.by_id(link_name)
        assert (element.start_node, element.end_node) == (
            link.start_node_name,
            link.end_node_name,
        )


def test_geojson_feature_collection_schema():
    topo = nt.import_network()
    fc = nt.feature_collection(topo.elements, metadata={"provenance": "synthetic"})
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 16
    by_id = {f["id"]: f for f in fc["features"]}
    assert by_id["R-PERM"]["geometry"]["type"] == "Point"
    assert by_id["P-MAIN"]["geometry"]["type"] == "LineString"
    for feature in fc["features"]:
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] in {"Point", "LineString"}
        assert feature["properties"]["canonical_asset_id"]


def test_nearest_returns_closest_element():
    topo = nt.import_network()
    georef = nt.GeoReference()
    lon, lat = georef.to_lonlat(0.0, 0.0)
    ranked = nt.nearest_elements(topo.elements, lon, lat, limit=1)
    assert ranked[0]["element"].element_id == "R-PERM"
    assert ranked[0]["distance_m"] < 1.0


def test_leak_localization_overlay_shape():
    topo = nt.import_network()
    overlay = nt.leak_localization_overlay(
        topo,
        [("J-D2", 6.0), ("J-D1", 3.0), ("J-D3", 1.5)],
        suspected_node_id="J-D2",
    )
    assert overlay["type"] == "FeatureCollection"
    assert overlay["metadata"]["status"] == "preliminary"
    assert overlay["metadata"]["provenance"] == "synthetic"
    features = overlay["features"]
    assert [f["properties"]["rank"] for f in features] == [1, 2, 3]
    assert all(f["geometry"]["type"] == "Polygon" for f in features)
    top = features[0]["properties"]
    assert top["node_id"] == "J-D2"
    assert top["suspected"] is True
    assert top["score"] == 1.0
