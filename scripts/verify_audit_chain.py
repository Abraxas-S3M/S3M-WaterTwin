#!/usr/bin/env python3
"""Verify the tamper-evident audit hash chain (standalone / post-restore check).

This re-walks the append-only audit chain and confirms every event's link and
content hash are intact. It is the off-host / DR counterpart to the API's
``GET /api/v1/audit/verify`` and mirrors the exact algorithm in
``services/watertwin-api/app/audit.py`` (guarded against drift by
``scripts/tests/test_verify_audit_chain.py``).

Sources of events (choose one):

* ``--database-url DSN`` — read ``audit_event`` (ordered by ``seq``) directly
  from a Postgres/TimescaleDB database (used against a *restored* database in the
  DR drill). Requires ``psycopg`` (imported lazily so the pure-JSON path has no
  dependencies).
* ``--json FILE`` / ``--stdin`` — verify a JSON array of event objects, e.g. one
  exported alongside a backup for off-host inspection.

Each event object must carry ``id``, ``ts``, ``kind``, ``actor``, ``subject``,
``payload``, ``prev_hash`` and ``hash``.

Exit code is ``0`` when the chain is intact and ``1`` when a break is found, so
the DR drill (and CI) can gate on it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any

# The chain anchor: the first event's prev_hash is the genesis hash.
GENESIS_HASH = "0" * 64

# Fields folded into each event's hash (prev_hash/hash are derived, excluded).
_HASHED_FIELDS = ("id", "ts", "kind", "actor", "subject", "payload")


def canonical(payload: Any) -> str:
    """Deterministic JSON encoding used as hash material (sorted, compact)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _event_core(event: dict[str, Any]) -> dict[str, Any]:
    return {field: event.get(field) for field in _HASHED_FIELDS}


def compute_hash(prev_hash: str, event: dict[str, Any]) -> str:
    """Compute the chain hash for ``event`` given the previous event's hash."""
    material = f"{prev_hash}{canonical(_event_core(event))}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def verify_chain(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify a hash chain of ``events`` given oldest-first."""
    prev_hash = GENESIS_HASH
    for index, event in enumerate(events):
        if event.get("prev_hash") != prev_hash:
            return {
                "ok": False,
                "broken_at": event.get("id"),
                "index": index,
                "count": len(events),
                "reason": "prev_hash mismatch (out-of-order or missing link)",
            }
        if compute_hash(prev_hash, event) != event.get("hash"):
            return {
                "ok": False,
                "broken_at": event.get("id"),
                "index": index,
                "count": len(events),
                "reason": "hash mismatch (event contents were altered)",
            }
        prev_hash = event["hash"]
    return {"ok": True, "count": len(events), "head": prev_hash}


def load_events_from_db(database_url: str) -> list[dict[str, Any]]:
    """Read the audit chain (oldest-first) from a database.

    Mirrors ``app.store.Store.audit_chain_asc`` so the read-back representation
    (``ts`` as ISO-8601, ``id`` as str, ``payload`` as a dict) matches what was
    hashed at write time.
    """
    import psycopg  # imported lazily: only the DB path needs it

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, ts, kind, actor, subject, payload, prev_hash, hash "
                "FROM audit_event ORDER BY seq ASC"
            )
            rows = cur.fetchall()
    return [
        {
            "id": str(r[0]),
            "ts": r[1].isoformat() if hasattr(r[1], "isoformat") else r[1],
            "kind": r[2],
            "actor": r[3],
            "subject": r[4],
            "payload": r[5],
            "prev_hash": r[6],
            "hash": r[7],
        }
        for r in rows
    ]


def _load_events(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.database_url:
        return load_events_from_db(args.database_url)
    if args.stdin:
        return json.load(sys.stdin)
    if args.json:
        with open(args.json, encoding="utf-8") as handle:
            return json.load(handle)
    raise SystemExit("provide one of --database-url, --json FILE, or --stdin")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--database-url", help="Postgres/Timescale DSN to read audit_event from.")
    src.add_argument("--json", help="Path to a JSON array of audit events.")
    src.add_argument("--stdin", action="store_true", help="Read a JSON array of events from stdin.")
    args = parser.parse_args(argv)

    events = _load_events(args)
    result = verify_chain(events)
    print(json.dumps(result, indent=2))
    if result["ok"]:
        print(f"OK: audit chain intact ({result['count']} event(s)).", file=sys.stderr)
        return 0
    print(
        f"::error::audit chain BROKEN at index {result['index']} "
        f"(event {result['broken_at']}): {result['reason']}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
