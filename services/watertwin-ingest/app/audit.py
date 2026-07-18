"""Tamper-evident, hash-chained, append-only audit trail for the ingest service.

Every meaningful action on an upload — received, scanned, parsed, quota-checked,
approved, deleted — is recorded as a linked event. Each event folds in the hash
of the previous event, so altering (or removing) any event invalidates every
hash after it and is detectable by re-walking the chain.

    hash = sha256(prev_hash + canonical(id, ts, kind, actor, subject, payload))

This mirrors the platform audit primitive in
``services/watertwin-api/app/audit.py`` and is reproduced here (not imported) so
the ingest service stays independently deployable — the platform must keep
working when this service is stopped. Nothing here writes to any control system.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

#: Chain anchor: the first event's ``prev_hash``.
GENESIS_HASH = "0" * 64

_HASHED_FIELDS = ("id", "ts", "kind", "actor", "subject", "payload")


def canonical(payload: Any) -> str:
    """Deterministic JSON encoding used as hash material."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _event_core(event: dict[str, Any]) -> dict[str, Any]:
    return {field_name: event.get(field_name) for field_name in _HASHED_FIELDS}


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


@dataclass
class AuditLog:
    """An in-memory, append-only hash-chained audit log.

    Events are scoped by ``tenant_id`` so a tenant only ever sees its own trail.
    The log is append-only: there is no update or delete of an event. Deleting an
    upload's *content* appends a ``deleted`` event — it never removes history.
    """

    _events: list[dict[str, Any]] = field(default_factory=list)

    def append(
        self,
        *,
        kind: str,
        actor: str,
        subject: str,
        tenant_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prev_hash = self._events[-1]["hash"] if self._events else GENESIS_HASH
        event: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "ts": time.time(),
            "kind": kind,
            "actor": actor,
            "subject": subject,
            "tenant_id": tenant_id,
            "payload": payload or {},
        }
        event["prev_hash"] = prev_hash
        event["hash"] = compute_hash(prev_hash, event)
        self._events.append(event)
        return event

    def events(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        if tenant_id is None:
            return list(self._events)
        return [e for e in self._events if e.get("tenant_id") == tenant_id]

    def verify(self) -> dict[str, Any]:
        """Verify the whole chain (all tenants, in append order)."""
        return verify_chain(self._events)

    def subject_trail(self, subject: str, *, tenant_id: str) -> list[dict[str, Any]]:
        """Return the ordered event trail for one upload within a tenant."""
        return [
            e
            for e in self._events
            if e.get("subject") == subject and e.get("tenant_id") == tenant_id
        ]
