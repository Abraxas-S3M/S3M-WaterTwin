"""Tests for the geospatial network twin.

Covers the three required checks:

* **Topology import parity with EPANET** -- the twin importer reproduces the same
  nodes/links/endpoints/coordinates as WNTR's own parse of the shared ``.inp``
  (and matches the hydraulic-sim element lists). A drift guard also asserts the
  bundled package model is byte-for-byte the model hydraulic-sim runs.
* **GeoJSON schema** -- feature collections are valid RFC 7946 with the expected
  geometry types and asset-linked properties.
* **Residual-overlay shape** -- the leak-localization overlay endpoint reuses the
  hydraulic-sim residual ranking and returns ranked candidate zones labelled
  preliminary + synthetic.
"""

from __future__ import annotations

import filecmp

import pytest
from fastapi.testclient import TestClient

from simulation_contracts import (
    LeakLocalization,
    ScenarioType,
    SimulationOutputs,
    SimulationResult,
)

import network_twin as nt
from network_twin import epanet_import


# --------------------------------------------------------------------------- #
# Topology import parity with EPANET
# --------------------------------------------------------------------------- #

EXPECTED_JUNCTIONS = {"J-PS", "J-PD", "J-HANDOFF", "J-D1", "J-D2", "J-D3"}
EXPECTED_RESERVOIRS = {"R-PERM"}
EXPECTED_TANKS = {"T-PROD"}
EXPECTED_PIPES = {"P-SUCT", "P-TANK", "P-MAIN", "P-D12", "P-D13"}
EXPECTED_PUMPS = {"PU-PROD-1", "PU-PROD-2"}
EXPECTED_VALVES = {"CV-HANDOFF"}


def _by_type(topo, element_type: str) -> set[str]:
    return {e.element_id for e in topo.elements if e.element_type.value == element_type}


def test_import_matches_expected_topology():
    topo = nt.import_network()
    assert _by_type(topo, "junction") == EXPECTED_JUNCTIONS
    assert _by_type(topo, "reservoir") == EXPECTED_RESERVOIRS
    assert _by_type(topo, "tank") == EXPECTED_TANKS
    assert _by_type(topo, "pipe") == EXPECTED_PIPES
    assert _by_type(topo, "pump") == EXPECTED_PUMPS
    assert _by_type(topo, "valve") == EXPECTED_VALVES
    assert len(topo.nodes) == 8
    assert len(topo.links) == 8


def test_bundled_model_does_not_drift_from_hydraulic_sim():
    # The twin and simulation must share topology: the bundled package model is
    # the exact model hydraulic-sim runs.
    assert filecmp.cmp(
        epanet_import.BUNDLED_INP, epanet_import.HYDRAULIC_SIM_INP, shallow=False
    )


def test_topology_parity_with_wntr():
    wntr = pytest.importorskip("wntr")
    wn = wntr.network.WaterNetworkModel(epanet_import.HYDRAULIC_SIM_INP)
    topo = nt.import_network()

    assert _by_type(topo, "junction") == set(wn.junction_name_list)
    assert _by_type(topo, "reservoir") == set(wn.reservoir_name_list)
    assert _by_type(topo, "tank") == set(wn.tank_name_list)
    assert _by_type(topo, "pipe") == set(wn.pipe_name_list)
    assert _by_type(topo, "pump") == set(wn.pump_name_list)
    assert _by_type(topo, "valve") == set(wn.valve_name_list)

    # Link endpoints match WNTR exactly.
    for link_name in wn.link_name_list:
        link = wn.get_link(link_name)
        element = topo.by_id(link_name)
        assert element is not None
        assert element.start_node == link.start_node_name
        assert element.end_node == link.end_node_name

    # Node schematic coordinates match WNTR exactly (before geo-referencing).
    for node_name in wn.node_name_list:
        node = wn.get_node(node_name)
        element = topo.by_id(node_name)
        assert element is not None
        assert tuple(element.properties["schematic_xy"]) == tuple(node.coordinates)


def test_elements_link_to_canonical_assets():
    topo = nt.import_network()
    # The two parallel product pumps link to a pre-existing canonical asset.
    for pump in EXPECTED_PUMPS:
        e = topo.by_id(pump)
        assert e.canonical_asset_id == "AST-BOOST-01"
        assert e.canonical_link is True
    # Elements with no pre-existing canonical asset are their own asset.
    r = topo.by_id("R-PERM")
    assert r.canonical_asset_id == "R-PERM"
    assert r.canonical_link is False


# --------------------------------------------------------------------------- #
# GeoJSON schema
# --------------------------------------------------------------------------- #


def _assert_valid_feature_collection(fc: dict) -> None:
    assert fc["type"] == "FeatureCollection"
    assert isinstance(fc["features"], list)
    for feature in fc["features"]:
        assert feature["type"] == "Feature"
        geom = feature["geometry"]
        assert geom["type"] in {"Point", "LineString", "Polygon"}
        assert isinstance(geom["coordinates"], list)
        props = feature["properties"]
        assert "element_id" in props or "node_id" in props


def test_feature_collection_geojson_schema():
    topo = nt.import_network()
    fc = nt.feature_collection(topo.elements, metadata={"provenance": "synthetic"})
    _assert_valid_feature_collection(fc)

    by_id = {f["id"]: f for f in fc["features"]}
    # Nodes are Points, links are LineStrings.
    assert by_id["R-PERM"]["geometry"]["type"] == "Point"
    assert by_id["P-MAIN"]["geometry"]["type"] == "LineString"
    # Point coordinates are WGS84 lon/lat pairs.
    lon, lat = by_id["R-PERM"]["geometry"]["coordinates"]
    assert -180 <= lon <= 180 and -90 <= lat <= 90
    # LineString endpoints reference the correct nodes.
    main = by_id["P-MAIN"]["properties"]
    assert main["start_node"] == "J-HANDOFF"
    assert main["end_node"] == "J-D1"
    assert main["canonical_asset_id"]


# --------------------------------------------------------------------------- #
# API endpoints (feature collections, per-asset lookup, nearest, overlay)
# --------------------------------------------------------------------------- #


class FakeHydraulicClient:
    """Deterministic hydraulic client that returns a leak result with residuals."""

    def health(self) -> dict:
        return {"status": "healthy", "service": "hydraulic-sim"}

    def network_info(self) -> dict:
        return {"train_id": "RO-TRAIN-001", "pumps": list(EXPECTED_PUMPS)}

    def run(
        self,
        scenario: ScenarioType,
        parameters=None,
        facility_id: str = "S3M-DESAL-01",
        train_id: str = "RO-TRAIN-001",
        requested_by=None,
    ) -> SimulationResult:
        localization = LeakLocalization(
            suspected_node_id="J-D2",
            residual_pressure_m=6.0,
            ranked_candidates=[("J-D2", 6.0), ("J-D1", 3.0), ("J-D3", 1.5)],
        )
        return SimulationResult(
            job_id="sim-leak0001",
            scenario=ScenarioType.leak,
            outputs=SimulationOutputs(
                delivered_flow_m3h=90.0, leak_localization=localization
            ),
            confidence=0.6,
        )


@pytest.fixture()
def api_client():
    from app.main import app, network_store

    app.state.hydraulic_client = FakeHydraulicClient()
    # Reset the in-memory twin so each test loads fresh.
    network_store._mem.clear()
    with TestClient(app) as c:
        yield c


def test_network_info_endpoint(api_client):
    body = api_client.get("/api/v1/network/").json()
    assert body["network_id"] == "ro-handoff"
    assert body["element_count"] == 16
    assert body["control_boundary"]["control_write_enabled"] is False
    assert body["geo_reference"]["synthetic"] is True
    assert body["storage"]["backend"] in {"in-memory", "postgis"}


def test_features_endpoint_and_filters(api_client):
    fc = api_client.get("/api/v1/network/features").json()
    _assert_valid_feature_collection(fc)
    assert len(fc["features"]) == 16

    pumps = api_client.get("/api/v1/network/features?element_type=pump").json()
    assert {f["id"] for f in pumps["features"]} == EXPECTED_PUMPS

    nodes = api_client.get("/api/v1/network/features?kind=node").json()
    assert len(nodes["features"]) == 8
    assert all(f["geometry"]["type"] == "Point" for f in nodes["features"])

    bad = api_client.get("/api/v1/network/features?element_type=widget")
    assert bad.status_code == 422


def test_per_asset_spatial_lookup(api_client):
    # By element id.
    fc = api_client.get("/api/v1/network/assets/T-PROD").json()
    assert len(fc["features"]) == 1
    assert fc["features"][0]["properties"]["element_type"] == "tank"

    # By canonical asset id: both product pumps resolve.
    fc = api_client.get("/api/v1/network/assets/AST-BOOST-01").json()
    assert {f["id"] for f in fc["features"]} == EXPECTED_PUMPS

    missing = api_client.get("/api/v1/network/assets/AST-NOPE-99")
    assert missing.status_code == 404


def test_nearest_lookup(api_client):
    georef = nt.GeoReference()
    lon, lat = georef.to_lonlat(0.0, 0.0)  # exactly at R-PERM's schematic origin
    body = api_client.get(
        f"/api/v1/network/nearest?lon={lon}&lat={lat}&limit=2"
    ).json()
    assert len(body["results"]) == 2
    assert body["results"][0]["feature"]["id"] == "R-PERM"
    assert body["results"][0]["distance_m"] < 1.0
    assert body["results"][0]["distance_m"] <= body["results"][1]["distance_m"]


def test_leak_localization_overlay_shape(api_client):
    overlay = api_client.get(
        "/api/v1/network/overlays/leak-localization?node_id=J-D2"
    ).json()

    assert overlay["type"] == "FeatureCollection"
    meta = overlay["metadata"]
    assert meta["overlay"] == "leak_localization"
    assert meta["status"] == "preliminary"
    assert meta["provenance"] == "synthetic"
    assert meta["suspected_node_id"] == "J-D2"
    assert meta["simulation_id"] == "sim-leak0001"
    assert meta["control_boundary"]["control_write_enabled"] is False

    features = overlay["features"]
    assert len(features) == 3
    # Zones are polygons ranked by residual (most-suspected first).
    ranks = [f["properties"]["rank"] for f in features]
    assert ranks == [1, 2, 3]
    residuals = [f["properties"]["residual_pressure_m"] for f in features]
    assert residuals == sorted(residuals, reverse=True)
    for f in features:
        assert f["geometry"]["type"] == "Polygon"
        props = f["properties"]
        assert props["kind"] == "leak_candidate_zone"
        assert props["status"] == "preliminary"
        assert props["provenance"] == "synthetic"
        assert 0.0 <= props["score"] <= 1.0
        assert props["radius_m"] > 0
    # The top candidate is flagged suspected and scores 1.0 (max residual).
    top = features[0]["properties"]
    assert top["node_id"] == "J-D2"
    assert top["suspected"] is True
    assert top["score"] == 1.0
