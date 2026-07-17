"""Tests for the standalone audit-chain verifier (DR / off-host check).

Covers:
  * a well-formed chain verifies and a tampered/broken one is detected; and
  * the standalone algorithm agrees byte-for-byte with the service module
    ``services/watertwin-api/app/audit.py`` (guards against drift, since the DR
    verifier must reproduce exactly what the API hashed at write time).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"
API_APP = REPO_ROOT / "services" / "watertwin-api"
for path in (str(SCRIPTS), str(API_APP)):
    if path not in sys.path:
        sys.path.insert(0, path)

import verify_audit_chain as verifier  # noqa: E402


def _build_chain(n: int) -> list[dict]:
    events: list[dict] = []
    prev = verifier.GENESIS_HASH
    for i in range(n):
        event = {
            "id": f"evt-{i}",
            "ts": f"2026-01-01T00:00:0{i}+00:00",
            "kind": "telemetry.ingested",
            "actor": "edge-gateway",
            "subject": f"gw-{i:012d}",
            "payload": {"batch_id": f"gw-{i:012d}", "reading_count": 7},
        }
        event["prev_hash"] = prev
        event["hash"] = verifier.compute_hash(prev, event)
        events.append(event)
        prev = event["hash"]
    return events


def test_intact_chain_verifies():
    events = _build_chain(5)
    result = verifier.verify_chain(events)
    assert result["ok"] is True
    assert result["count"] == 5


def test_empty_chain_is_valid():
    assert verifier.verify_chain([]) == {
        "ok": True,
        "count": 0,
        "head": verifier.GENESIS_HASH,
    }


def test_tampered_payload_is_detected():
    events = _build_chain(4)
    events[2]["payload"]["reading_count"] = 999  # edit a stored field
    result = verifier.verify_chain(events)
    assert result["ok"] is False
    assert result["broken_at"] == "evt-2"
    assert result["index"] == 2


def test_deleted_event_breaks_the_link():
    events = _build_chain(4)
    del events[1]
    assert verifier.verify_chain(events)["ok"] is False


def test_agrees_with_service_audit_module():
    # The DR verifier must compute identical hashes to the running service.
    from app import audit as service_audit

    event = {
        "id": "evt-x",
        "ts": "2026-07-17T14:38:00.123456+00:00",
        "kind": "telemetry.ingested",
        "actor": "edge-gateway",
        "subject": "gw-000000000042",
        "payload": {"batch_id": "gw-000000000042", "reading_count": 7, "nested": {"b": 2, "a": 1}},
    }
    prev = "a" * 64
    assert verifier.compute_hash(prev, event) == service_audit.compute_hash(prev, event)
    assert verifier.GENESIS_HASH == service_audit.GENESIS_HASH
    assert verifier.canonical({"b": 1, "a": 2}) == service_audit.canonical({"b": 1, "a": 2})
