"""Tests for the tag-normalization layer + ingestion endpoints.

Fast and dependency-free: they exercise the customer-tag -> canonical mapping
(scale/offset, validation, rejection), the shipped sample tag map, the
normalize-preview endpoint and the active-source status endpoint.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import tag_normalization as tn
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# --- Normalization engine ---------------------------------------------------


def _sample_map() -> tn.TagMap:
    return tn.TagMap.from_dict(
        {
            "map_id": "unit-test-map",
            "tags": {
                "CUST.PUMP.TEMP_F": {
                    "asset_id": "AST-HPP-01",
                    "metric": "winding_temp_c",
                    "unit": "degC",
                    "scale": 0.5555556,
                    "offset": -17.7778,
                },
                "CUST.PUMP.VIB": {
                    "asset_id": "AST-HPP-01",
                    "metric": "vibration_mm_s",
                    "unit": "mm/s",
                },
            },
        }
    )


def test_maps_customer_tag_to_canonical_with_unit_and_scale():
    tag_map = _sample_map()
    result = tn.normalize(
        [tn.RawReading(customer_tag="CUST.PUMP.TEMP_F", value=302.0)], tag_map
    )
    assert not result.rejected
    assert len(result.readings) == 1
    reading = result.readings[0]
    assert reading.asset_id == "AST-HPP-01"
    assert reading.metric == "winding_temp_c"
    assert reading.unit == "degC"
    # 302 F == 150 C, applied via scale/offset.
    assert reading.value == pytest.approx(150.0, abs=1e-2)
    # Real OT feed data is stamped measured.
    assert reading.provenance.value == "measured"


def test_default_scale_and_offset_are_identity():
    tag_map = _sample_map()
    result = tn.normalize([tn.RawReading("CUST.PUMP.VIB", 6.4)], tag_map)
    assert result.readings[0].value == pytest.approx(6.4)


def test_unmapped_tag_is_rejected():
    tag_map = _sample_map()
    result = tn.normalize([tn.RawReading("NOT.IN.MAP", 1.0)], tag_map)
    assert result.readings == []
    assert len(result.rejected) == 1
    assert result.rejected[0].customer_tag == "NOT.IN.MAP"
    assert result.rejected[0].reason == "unmapped tag"


def test_non_numeric_value_is_rejected():
    tag_map = _sample_map()
    result = tn.normalize([tn.RawReading("CUST.PUMP.VIB", "not-a-number")], tag_map)
    assert result.readings == []
    assert result.rejected[0].reason == "non-numeric value"


def test_invalid_tag_map_missing_field_raises():
    with pytest.raises(tn.TagMapError):
        tn.TagMap.from_dict({"tags": {"X": {"asset_id": "A", "metric": "m"}}})  # no unit


def test_shipped_sample_tag_map_loads():
    tag_map = tn.load_tag_map("example-plant")
    assert tag_map.map_id == "example-plant-v1"
    assert "PLC1.HPP_A.WINDING_TEMP" in tag_map.entries


# --- Endpoints --------------------------------------------------------------


def test_preview_named_map_maps_and_rejects(client):
    resp = client.post(
        "/api/v1/ingestion/normalize/preview",
        json={
            "tag_map": "example-plant",
            "readings": [
                {"customer_tag": "PLC1.HPP_A.WINDING_TEMP_F", "value": 302.0},
                {"customer_tag": "UNKNOWN.TAG", "value": 1.0},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"] == {"total": 2, "mapped": 1, "rejected": 1}
    reading = body["readings"][0]
    assert reading["asset_id"] == "AST-HPP-01"
    assert reading["metric"] == "winding_temp_c"
    assert reading["unit"] == "degC"
    assert reading["value"] == pytest.approx(150.0, abs=1e-2)
    assert body["rejected"][0]["customer_tag"] == "UNKNOWN.TAG"
    assert body["control_boundary"]["control_write_enabled"] is False


def test_preview_inline_map(client):
    resp = client.post(
        "/api/v1/ingestion/normalize/preview",
        json={
            "tag_map_inline": {
                "tags": {
                    "T1": {"asset_id": "AST-CF-01", "metric": "dp_bar", "unit": "bar", "scale": 0.001}
                }
            },
            "readings": [{"customer_tag": "T1", "value": 570}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["readings"][0]["value"] == pytest.approx(0.57)


def test_preview_requires_a_tag_map(client):
    resp = client.post(
        "/api/v1/ingestion/normalize/preview",
        json={"readings": [{"customer_tag": "T1", "value": 1}]},
    )
    assert resp.status_code == 422


def test_preview_invalid_inline_map_is_422(client):
    resp = client.post(
        "/api/v1/ingestion/normalize/preview",
        json={"tag_map_inline": {"tags": {"T1": {"asset_id": "A"}}}, "readings": []},
    )
    assert resp.status_code == 422


def test_source_endpoint_reports_synthetic_default(client):
    body = client.get("/api/v1/ingestion/source").json()
    assert body["active_source"] == "synthetic"
    assert body["requested_source"] == "synthetic"
    assert body["fallback"] is False
    assert set(body["available_sources"]) == {"synthetic", "opcua", "modbus", "historian"}
    assert body["control_boundary"]["control_write_enabled"] is False
