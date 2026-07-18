"""The audit client produces a hash chain in watertwin-api's exact format."""

from __future__ import annotations

import hashlib
import json

from app.audit_client import (
    GENESIS_HASH,
    AuditClient,
    InMemoryAuditTransport,
    compute_hash,
)


def _reference_hash(prev_hash: str, event: dict) -> str:
    """Independent reimplementation of watertwin-api's chain hash (audit.py)."""
    core = {field: event.get(field) for field in ("id", "ts", "kind", "actor", "subject", "payload")}
    canonical = json.dumps(core, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{prev_hash}{canonical}".encode()).hexdigest()


def test_compute_hash_matches_reference_format():
    event = {
        "id": "abc",
        "ts": "2026-01-01T00:00:00+00:00",
        "kind": "ingest.received",
        "actor": "erin-engineer",
        "subject": "ingest-1",
        "payload": {"b": 2, "a": 1},
    }
    assert compute_hash(GENESIS_HASH, event) == _reference_hash(GENESIS_HASH, event)


def test_client_builds_a_linked_chain():
    audit = AuditClient(InMemoryAuditTransport())
    first = audit.record(kind="ingest.received", actor="erin", subject="s1", payload={"x": 1})
    second = audit.record(kind="ingest.status_transition", actor="erin", subject="s1")

    # First entry chains to genesis; the second chains to the first.
    assert first["prev_hash"] == GENESIS_HASH
    assert second["prev_hash"] == first["hash"]
    assert audit.head == second["hash"]

    # Each stored hash is a valid recomputation over its core fields.
    for entry in audit.transport.entries:
        assert entry["hash"] == _reference_hash(entry["prev_hash"], entry)
    # Required identity-bearing fields are present.
    assert {"id", "ts", "kind", "actor", "subject", "payload", "prev_hash", "hash"} <= set(
        first
    )


def test_tampering_breaks_the_chain():
    audit = AuditClient(InMemoryAuditTransport())
    entry = audit.record(kind="ingest.received", actor="erin", subject="s1", payload={"v": 1})
    tampered = dict(entry)
    tampered["payload"] = {"v": 999}
    assert compute_hash(tampered["prev_hash"], tampered) != entry["hash"]
