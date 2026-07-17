"""Usage-metering tests: counts and billing export.

Verify the metered dimensions (facilities, assets, ingest volume) count
correctly — including distinct de-duplication — both at the meter level and
through the API (ingest volume via the read-only ingestion path; the admin
usage + billing-export endpoints).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.metering import UsageMeter, meter


@pytest.fixture()
def client():
    meter.reset()
    with TestClient(app) as c:
        yield c


# --- Meter unit -------------------------------------------------------------


def test_meter_counts_distinct_facilities_and_assets():
    m = UsageMeter()
    m.record_facility("S3M-DESAL-01")
    m.record_facility("S3M-DESAL-01")  # duplicate -> still one
    m.record_facility("S3M-DESAL-02")
    m.record_asset("AST-HPP-01")
    m.record_asset("AST-HPP-01")  # duplicate -> still one
    m.record_asset("AST-CF-01")

    snap = m.snapshot()
    assert snap["facilities"] == 2
    assert snap["assets"] == 2


def test_meter_counts_ingest_volume():
    m = UsageMeter()
    m.record_ingest(3)
    m.record_ingest(5)
    m.record_ingest(0)  # ignored
    m.record_ingest(-2)  # ignored
    assert m.snapshot()["ingest_events"] == 8


def test_meter_ignores_empty_ids():
    m = UsageMeter()
    m.record_facility(None)
    m.record_facility("")
    m.record_asset(None)
    snap = m.snapshot()
    assert snap["facilities"] == 0
    assert snap["assets"] == 0


def test_billing_export_reports_limits_and_within_flag():
    m = UsageMeter()
    m.record_asset("AST-HPP-01")
    m.record_asset("AST-CF-01")
    m.record_asset("AST-RO-01")
    export = m.billing_export(
        tenant_id="acme", plan="standard", limits={"max_assets": 2}
    )
    assert export["tenant_id"] == "acme"
    assert export["plan"] == "standard"
    assets_row = next(r for r in export["metrics"] if r["metric"] == "assets")
    assert assets_row["quantity"] == 3
    assert assets_row["limit"] == 2
    assert assets_row["within_limit"] is False


# --- Through the API --------------------------------------------------------


def _inline_tag_map() -> dict:
    return {
        "map_id": "test-inline",
        "tags": {
            "PLC1.HPP.TEMP": {
                "asset_id": "AST-HPP-01",
                "metric": "winding_temp_c",
                "unit": "degC",
            }
        },
    }


def test_ingest_volume_metered_via_ingestion_endpoint(client):
    assert client.get("/api/v1/admin/metering/usage").json()["usage"]["ingest_events"] == 0

    resp = client.post(
        "/api/v1/ingestion/normalize/preview",
        json={
            "tag_map_inline": _inline_tag_map(),
            "readings": [
                {"customer_tag": "PLC1.HPP.TEMP", "value": 150.0},
                {"customer_tag": "PLC1.HPP.TEMP", "value": 151.0},
                {"customer_tag": "UNKNOWN.TAG", "value": 1.0},
            ],
        },
    )
    assert resp.status_code == 200

    usage = client.get("/api/v1/admin/metering/usage").json()["usage"]
    # All three readings brought in count toward ingest volume (even the
    # rejected one — it still consumed ingest bandwidth).
    assert usage["ingest_events"] == 3


def test_equipment_reads_meter_distinct_assets(client):
    client.get("/api/v1/equipment/AST-HPP-01/health")
    client.get("/api/v1/equipment/AST-HPP-01/rul")  # same asset
    client.get("/api/v1/equipment/AST-CF-01/health")

    usage = client.get("/api/v1/admin/metering/usage").json()["usage"]
    assert usage["assets"] == 2
    assert set(usage["asset_ids"]) == {"AST-HPP-01", "AST-CF-01"}


def test_admin_billing_export_endpoint(client):
    client.get("/api/v1/equipment/AST-HPP-01/health")
    body = client.get("/api/v1/admin/metering/billing-export").json()
    export = body["billing_export"]
    assert {r["metric"] for r in export["metrics"]} == {
        "facilities",
        "assets",
        "ingest_events",
    }
    assert body["control_boundary"]["control_write_enabled"] is False
