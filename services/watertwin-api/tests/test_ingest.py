"""Tests for the telemetry ingest sink (the edge-gateway's outbound target).

The ingest endpoint accepts a pushed batch of canonical telemetry, mirrors the
newest reading per signal, records the pushing gateway's source health, and
audits the batch. It is advisory data only -- it never writes to any control
system, so every response carries the read-only control boundary.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        # Start from a clean ingest mirror.
        c.post("/api/v1/reset")
        yield c


def _batch(**overrides):
    batch = {
        "gateway_id": "edge-gw-01",
        "source": "modbus",
        "fallback": False,
        "source_health": {"status": "healthy", "consecutive_failures": 0},
        "sent_at": "2026-01-01T00:00:00+00:00",
        "readings": [
            {
                "asset_id": "AST-HPP-01",
                "metric": "winding_temp_c",
                "value": 150.0,
                "unit": "degC",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "provenance": "measured",
                "quality": "good",
            },
            {
                "asset_id": "AST-HPP-01",
                "metric": "vibration_mm_s",
                "value": 6.4,
                "unit": "mm/s",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "provenance": "measured",
                "quality": "good",
            },
        ],
    }
    batch.update(overrides)
    return batch


def test_ingest_accepts_batch_and_mirrors_latest(client):
    resp = client.post("/api/v1/ingestion/telemetry", json=_batch())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["accepted"] == 2
    assert body["rejected"] == []
    assert body["control_boundary"]["control_write_enabled"] is False

    latest = client.get("/api/v1/ingestion/telemetry/latest").json()
    assert latest["count"] == 2
    signals = {(r["asset_id"], r["metric"]): r for r in latest["readings"]}
    assert signals[("AST-HPP-01", "winding_temp_c")]["value"] == pytest.approx(150.0)
    assert signals[("AST-HPP-01", "winding_temp_c")]["quality"] == "good"
    assert signals[("AST-HPP-01", "winding_temp_c")]["gateway_id"] == "edge-gw-01"

    gateways = {g["gateway_id"]: g for g in latest["gateways"]}
    assert gateways["edge-gw-01"]["source"] == "modbus"
    assert gateways["edge-gw-01"]["source_health"]["status"] == "healthy"


def test_ingest_upserts_newest_reading_per_signal(client):
    client.post("/api/v1/ingestion/telemetry", json=_batch())
    newer = _batch(
        readings=[
            {
                "asset_id": "AST-HPP-01",
                "metric": "winding_temp_c",
                "value": 151.5,
                "unit": "degC",
                "timestamp": "2026-01-01T00:05:00+00:00",
                "provenance": "measured",
                "quality": "good",
            }
        ]
    )
    client.post("/api/v1/ingestion/telemetry", json=newer)
    latest = client.get("/api/v1/ingestion/telemetry/latest").json()
    signals = {(r["asset_id"], r["metric"]): r for r in latest["readings"]}
    assert signals[("AST-HPP-01", "winding_temp_c")]["value"] == pytest.approx(151.5)


def test_ingest_records_fallback_and_audits(client):
    client.post("/api/v1/ingestion/telemetry", json=_batch(source="synthetic", fallback=True))
    latest = client.get("/api/v1/ingestion/telemetry/latest").json()
    gateways = {g["gateway_id"]: g for g in latest["gateways"]}
    assert gateways["edge-gw-01"]["fallback"] is True

    audit = client.get("/api/v1/audit").json()
    kinds = [e["kind"] for e in audit["events"]]
    assert "telemetry.ingested" in kinds
