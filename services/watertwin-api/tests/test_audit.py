"""Tests for the tamper-evident (hash-chained, append-only) audit trail.

These exercise the in-memory fallback path (no database configured) which is
the mode the test-suites and local dev run in, plus the pure chain primitives
in :mod:`app.audit` and the ``/api/v1/audit/verify`` endpoint.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import audit as audit_chain
from app.store import Store


@pytest.fixture()
def store() -> Store:
    # No database URL -> pure in-memory hash chain.
    return Store(database_url=None, connect=False)


def test_appending_events_builds_a_valid_chain(store: Store):
    for i in range(5):
        store.audit("scenario.run", payload={"i": i}, actor=f"user-{i}")

    events = store.audit_chain_asc()
    assert len(events) == 5

    # First event links to genesis; each subsequent event links to its
    # predecessor's hash.
    assert events[0]["prev_hash"] == audit_chain.GENESIS_HASH
    for prev, cur in zip(events, events[1:]):
        assert cur["prev_hash"] == prev["hash"]

    result = store.verify_chain()
    assert result["ok"] is True
    assert result["count"] == 5


def test_empty_chain_is_valid(store: Store):
    assert store.verify_chain() == {
        "ok": True,
        "count": 0,
        "head": audit_chain.GENESIS_HASH,
    }


def test_tampering_with_a_stored_payload_breaks_the_chain(store: Store):
    store.audit("scenario.run", payload={"amount": 1}, actor="a")
    store.audit("recommendation.decision", payload={"amount": 2}, actor="b")
    store.audit("report.generated", payload={"amount": 3}, actor="c")
    assert store.verify_chain()["ok"] is True

    # Tamper with the middle event's payload in place (simulating an attacker
    # editing the stored row without recomputing hashes).
    tampered = store._audit_mem[1]
    tampered["payload"]["amount"] = 999_999

    result = store.verify_chain()
    assert result["ok"] is False
    assert result["broken_at"] == tampered["id"]
    assert result["index"] == 1


def test_tampering_with_actor_is_detected(store: Store):
    store.audit("scenario.run", payload={}, actor="a")
    store.audit("scenario.run", payload={}, actor="b")

    store._audit_mem[0]["actor"] = "attacker"
    result = store.verify_chain()
    assert result["ok"] is False
    assert result["index"] == 0


def test_deleting_an_event_breaks_the_chain(store: Store):
    store.audit("e1", payload={})
    store.audit("e2", payload={})
    store.audit("e3", payload={})

    # Remove the middle event: the following event's prev_hash no longer matches.
    del store._audit_mem[1]
    result = store.verify_chain()
    assert result["ok"] is False


def test_canonical_is_order_independent():
    a = audit_chain.canonical({"b": 1, "a": 2})
    b = audit_chain.canonical({"a": 2, "b": 1})
    assert a == b


def test_reset_reanchors_the_chain(store: Store):
    store.audit("e1", payload={})
    store.reset()
    assert store.verify_chain()["count"] == 0
    # New events after reset chain from genesis again.
    store.audit("e2", payload={})
    events = store.audit_chain_asc()
    assert events[0]["prev_hash"] == audit_chain.GENESIS_HASH
    assert store.verify_chain()["ok"] is True


def test_verify_endpoint_reports_ok_and_break():
    from app.main import app

    with TestClient(app) as client:
        client.post("/api/v1/reset")

        ok = client.get("/api/v1/audit/verify")
        assert ok.status_code == 200
        # The reset itself is audited, so the chain is non-empty and valid.
        assert ok.json()["ok"] is True

        # Tamper directly with the in-memory store backing the app, then verify
        # the endpoint reports the break.
        from app.main import store as app_store

        assert app_store._audit_mem, "expected at least the reset audit event"
        app_store._audit_mem[0]["payload"]["tampered"] = True

        broken = client.get("/api/v1/audit/verify")
        assert broken.status_code == 200
        body = broken.json()
        assert body["ok"] is False
        assert body["broken_at"] == app_store._audit_mem[0]["id"]

        # Clean up so we don't leave a broken chain for other tests.
        client.post("/api/v1/reset")
