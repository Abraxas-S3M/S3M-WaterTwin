"""Tests for the telemetry ingest write path (edge store-and-forward destination).

These exercise the in-memory store path (the mode the suites run in) plus the
``POST /api/v1/ingestion/telemetry`` endpoint, its idempotency-on-``batch_id``
guarantee, ingest-token auth, and the invariant that ingest keeps the
tamper-evident audit chain valid.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.store import Store


def _reading(asset_id: str = "PU-PROD-1", metric: str = "vibration_mm_s", value: float = 3.2) -> dict:
    return {
        "asset_id": asset_id,
        "metric": metric,
        "value": value,
        "unit": "mm/s",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "provenance": "synthetic",
        "quality": "good",
    }


@pytest.fixture()
def store() -> Store:
    return Store(database_url=None, connect=False)


def test_ingest_appends_readings_and_one_audit_event(store: Store):
    result = store.ingest_telemetry("gw-0000000001", [_reading(), _reading(metric="winding_temp_c")])

    assert result["duplicate"] is False
    assert result["accepted"] == 2
    assert result["audit_id"] is not None

    assert store.telemetry_stats() == {"batches": 1, "readings": 2}

    # Exactly one audit event, and the chain is valid and binds the batch.
    events = store.audit_chain_asc()
    assert len(events) == 1
    assert events[0]["kind"] == "telemetry.ingested"
    assert events[0]["payload"]["batch_id"] == "gw-0000000001"
    assert events[0]["payload"]["reading_count"] == 2
    assert store.verify_chain()["ok"] is True


def test_ingest_is_idempotent_on_batch_id(store: Store):
    first = store.ingest_telemetry("gw-0000000001", [_reading(), _reading()])
    replay = store.ingest_telemetry("gw-0000000001", [_reading(), _reading()])

    assert first["duplicate"] is False
    assert replay["duplicate"] is True
    assert replay["accepted"] == 0

    # No double-write of readings, and only one audit event for the batch.
    assert store.telemetry_stats() == {"batches": 1, "readings": 2}
    assert len(store.audit_chain_asc()) == 1
    assert store.verify_chain()["ok"] is True


def test_many_batches_keep_the_chain_valid(store: Store):
    for seq in range(1, 26):
        store.ingest_telemetry(f"gw-{seq:010d}", [_reading(value=float(seq))])

    stats = store.telemetry_stats()
    assert stats == {"batches": 25, "readings": 25}
    result = store.verify_chain()
    assert result["ok"] is True
    assert result["count"] == 25


def test_replaying_a_spool_after_a_crash_is_lossless_and_duplicate_free(store: Store):
    # Simulate an edge gateway that produced batches 1..10 but only got an ack
    # for 1..6 before a crash; on restart it replays its durable spool 4..10.
    produced = [f"gw-{seq:010d}" for seq in range(1, 11)]
    for batch_id in produced[:6]:
        store.ingest_telemetry(batch_id, [_reading()])

    # Replay overlaps the already-acked 4..6 and delivers the rest.
    for batch_id in produced[3:]:
        store.ingest_telemetry(batch_id, [_reading()])

    stats = store.telemetry_stats()
    assert stats["batches"] == 10  # every distinct batch landed exactly once
    assert stats["readings"] == 10  # no duplication from the overlap
    assert store.verify_chain()["ok"] is True


# --------------------------------------------------------------------------- #
# Endpoint behaviour
# --------------------------------------------------------------------------- #


def test_ingest_endpoint_and_stats(monkeypatch):
    monkeypatch.delenv("WATERTWIN_INGEST_TOKEN", raising=False)
    from app.main import app

    with TestClient(app) as client:
        client.post("/api/v1/reset")

        body = {
            "batch_id": "edge-gw-01-0000000001",
            "readings": [_reading(), _reading(metric="discharge_pressure_bar", value=61.0)],
            "source": "edge-gw-01",
        }
        resp = client.post("/api/v1/ingestion/telemetry", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["duplicate"] is False
        assert data["accepted"] == 2
        assert data["control_boundary"]["control_write_enabled"] is False

        # Replay is a no-op.
        replay = client.post("/api/v1/ingestion/telemetry", json=body)
        assert replay.status_code == 200
        assert replay.json()["duplicate"] is True

        stats = client.get("/api/v1/ingestion/telemetry/stats")
        assert stats.status_code == 200
        assert stats.json()["batches"] == 1
        assert stats.json()["readings"] == 2

        assert client.get("/api/v1/audit/verify").json()["ok"] is True
        client.post("/api/v1/reset")


def test_ingest_endpoint_rejects_empty_batch(monkeypatch):
    monkeypatch.delenv("WATERTWIN_INGEST_TOKEN", raising=False)
    from app.main import app

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/ingestion/telemetry",
            json={"batch_id": "empty-batch", "readings": []},
        )
        assert resp.status_code == 422


def test_ingest_token_is_enforced_when_configured(monkeypatch):
    monkeypatch.setenv("WATERTWIN_INGEST_TOKEN", "s3cr3t-ingest")
    from app.main import app

    body = {"batch_id": "tok-0000000001", "readings": [_reading()]}
    with TestClient(app) as client:
        client.post("/api/v1/reset")

        # Missing token -> 401.
        assert client.post("/api/v1/ingestion/telemetry", json=body).status_code == 401
        # Wrong token -> 401.
        bad = client.post(
            "/api/v1/ingestion/telemetry", json=body, headers={"X-Ingest-Token": "nope"}
        )
        assert bad.status_code == 401
        # Correct token -> accepted.
        ok = client.post(
            "/api/v1/ingestion/telemetry",
            json=body,
            headers={"X-Ingest-Token": "s3cr3t-ingest"},
        )
        assert ok.status_code == 200
        assert ok.json()["accepted"] == 1
        client.post("/api/v1/reset")
