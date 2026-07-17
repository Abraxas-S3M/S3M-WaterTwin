"""Tamper-evident audit primitives (hash-chained, append-only).

The audit trail is a linked chain of events. Each event carries the hash of the
previous event (``prev_hash``) and its own ``hash``:

    hash = sha256(prev_hash + canonical(event_core))

``event_core`` is the canonical (deterministic) JSON of the event's
identity-bearing fields (``id``, ``ts``, ``kind``, ``actor``, ``subject`` and
``payload``). Because every hash folds in the previous hash, altering any stored
field of any event — most importantly its ``payload`` — invalidates that event's
hash *and* every hash after it, so tampering is detectable by re-walking the
chain (:func:`verify_chain`).

This module is pure and side-effect free; :mod:`app.store` uses it to build and
verify the chain in both the database-backed and in-memory modes. Nothing here
writes to any control system — the audit trail records advisory actions only.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# The chain anchor. The first event's ``prev_hash`` is the genesis hash so an
# empty chain has a well-defined head.
GENESIS_HASH = "0" * 64

# Fields that are hashed into the chain. ``prev_hash`` and ``hash`` are excluded
# (they are derived), everything else that identifies the event is included so a
# change to any of them is detectable.
_HASHED_FIELDS = ("id", "ts", "kind", "actor", "subject", "payload")


def canonical(payload: Any) -> str:
    """Return a deterministic JSON encoding used as hash material.

    Keys are sorted and separators are compact so the same logical value always
    produces the same bytes regardless of dict insertion order or whitespace.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _event_core(event: dict[str, Any]) -> dict[str, Any]:
    return {field: event.get(field) for field in _HASHED_FIELDS}


def compute_hash(prev_hash: str, event: dict[str, Any]) -> str:
    """Compute the chain hash for ``event`` given the previous event's hash."""
    material = f"{prev_hash}{canonical(_event_core(event))}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def link_event(event: dict[str, Any], prev_hash: str) -> dict[str, Any]:
    """Attach ``prev_hash`` and the derived ``hash`` to ``event`` in place."""
    event["prev_hash"] = prev_hash
    event["hash"] = compute_hash(prev_hash, event)
    return event


def verify_chain(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify a hash chain of ``events`` given oldest-first.

    Returns ``{"ok": True, "count": n}`` when the chain is intact. When a break
    is found, returns ``{"ok": False, "broken_at": <event id>, "index": <i>,
    "count": n, "reason": ...}`` identifying the first event that fails
    validation (either its recorded ``prev_hash`` does not match the running
    head, or its stored ``hash`` does not match a recomputation of its
    contents — i.e. the payload or another field was altered).
    """
    prev_hash = GENESIS_HASH
    for index, event in enumerate(events):
        recorded_prev = event.get("prev_hash")
        if recorded_prev != prev_hash:
            return {
                "ok": False,
                "broken_at": event.get("id"),
                "index": index,
                "count": len(events),
                "reason": "prev_hash mismatch (out-of-order or missing link)",
            }
        recomputed = compute_hash(prev_hash, event)
        if recomputed != event.get("hash"):
            return {
                "ok": False,
                "broken_at": event.get("id"),
                "index": index,
                "count": len(events),
                "reason": "hash mismatch (event contents were altered)",
            }
        prev_hash = event["hash"]
    return {"ok": True, "count": len(events), "head": prev_hash}
