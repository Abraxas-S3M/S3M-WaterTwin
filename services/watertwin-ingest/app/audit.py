"""Tamper-evident audit chain for the data-intake service.

Mirrors the hash-chaining scheme used by ``services/watertwin-api/app/audit.py``:
every event folds in the previous event's hash, so altering any recorded field
(most importantly the model version or the analysis payload) is detectable by
re-walking the chain. This lets an answer be reconstructed and verified later.

Records advisory actions only; nothing here writes to any control system.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from typing import Any

from canonical_water_model import now_iso

GENESIS_HASH = "0" * 64
_HASHED_FIELDS = ("id", "ts", "kind", "actor", "subject", "payload")

KIND_ANALYSIS_REQUEST = "ingest.analysis.request"
KIND_ANALYSIS_RESPONSE = "ingest.analysis.response"


def canonical(payload: Any) -> str:
    """Deterministic JSON encoding used as hash material."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, event: dict[str, Any]) -> str:
    """Compute the chain hash for ``event`` given the previous event's hash."""
    core = {field: event.get(field) for field in _HASHED_FIELDS}
    material = f"{prev_hash}{canonical(core)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuditChain:
    """An append-only, hash-chained audit log (in-memory)."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._counter = itertools.count(1)

    @property
    def head(self) -> str:
        return self._events[-1]["hash"] if self._events else GENESIS_HASH

    def append(
        self,
        *,
        kind: str,
        actor: str,
        subject: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Append an event and return it (with ``prev_hash`` + ``hash`` set)."""
        event: dict[str, Any] = {
            "id": f"evt-{next(self._counter)}",
            "ts": now_iso(),
            "kind": kind,
            "actor": actor,
            "subject": subject,
            "payload": payload,
        }
        prev_hash = self.head
        event["prev_hash"] = prev_hash
        event["hash"] = compute_hash(prev_hash, event)
        self._events.append(event)
        return event

    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def verify(self) -> dict[str, Any]:
        """Verify the chain integrity; returns ``{"ok": True, ...}`` when intact."""
        prev_hash = GENESIS_HASH
        for index, event in enumerate(self._events):
            if event.get("prev_hash") != prev_hash:
                return {"ok": False, "broken_at": event.get("id"), "index": index}
            if compute_hash(prev_hash, event) != event.get("hash"):
                return {"ok": False, "broken_at": event.get("id"), "index": index}
            prev_hash = event["hash"]
        return {"ok": True, "count": len(self._events), "head": prev_hash}


#: Process-wide default chain for the analysis endpoint.
_chain: AuditChain | None = None


def get_audit_chain() -> AuditChain:
    global _chain
    if _chain is None:
        _chain = AuditChain()
    return _chain
