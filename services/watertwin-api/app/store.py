"""Durable audit + recommendation store with a graceful in-memory fallback.

Phase 10 persistence layer. When ``WATERTWIN_DATABASE_URL`` points at a reachable
Postgres/TimescaleDB instance the store writes audit events and recommendation
records to it (schema created by ``infrastructure/database/init.sql``, and also
ensured idempotently here). When no database is configured or reachable the
store operates purely in memory and reports ``db_connected == False`` so the
service and its tests run without infrastructure.

Nothing in this module writes to any control system; it persists advisory
artifacts (recommendations, approvals, audit trail) only.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from . import audit as audit_chain

logger = logging.getLogger("watertwin.store")


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


# The audit table is a tamper-evident, append-only hash chain. Each row records
# the hash of the previous row (``prev_hash``) and its own ``hash`` so any edit
# to a stored event is detectable (see ``app.audit``). ``seq`` gives a
# deterministic append order for chain verification. The append-only invariant
# is additionally enforced at the database layer by a trigger in
# ``infrastructure/database/init.sql`` (updates/deletes are rejected).
_CREATE_AUDIT = """
CREATE TABLE IF NOT EXISTS audit_event (
    seq BIGSERIAL,
    id UUID PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    subject TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    prev_hash TEXT NOT NULL DEFAULT '',
    hash TEXT NOT NULL DEFAULT ''
);
"""

# Backfill columns/ordering for databases created before the hash chain existed.
_MIGRATE_AUDIT = (
    "ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS seq BIGSERIAL",
    "ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS prev_hash TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS hash TEXT NOT NULL DEFAULT ''",
)

# Append-only guard: reject row updates/deletes on the audit trail. TRUNCATE
# (used only by the demo ``reset``) is intentionally not blocked here.
_APPEND_ONLY_GUARD = """
CREATE OR REPLACE FUNCTION audit_event_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_event is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_event_no_mutation ON audit_event;
CREATE TRIGGER audit_event_no_mutation
    BEFORE UPDATE OR DELETE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION audit_event_reject_mutation();
"""

_CREATE_RECOMMENDATION = """
CREATE TABLE IF NOT EXISTS recommendation (
    recommendation_id TEXT PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    facility_id TEXT,
    train_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    card JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""


class Store:
    """Audit + recommendation persistence with graceful in-memory fallback."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        connect: bool = True,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.database_url = database_url or None
        self.db_connected = False
        self._conn: Any = None
        self._lock = threading.RLock()
        # Optional advisory hook invoked (outside the store lock) after an audit
        # event is successfully appended. Used to emit the ``audit-appended``
        # service event. Never a control-write path; failures are swallowed by
        # the caller so persistence is unaffected by a bus outage.
        self._event_sink = event_sink

        # In-memory mirrors used whenever the database is unavailable.
        self._audit_mem: list[dict[str, Any]] = []
        self._rec_mem: dict[str, dict[str, Any]] = {}

        # Running head of the in-memory audit hash chain (genesis when empty).
        self._chain_head: str = audit_chain.GENESIS_HASH

        if connect and self.database_url:
            self._try_connect(self.database_url)

    # -- connection lifecycle -------------------------------------------------

    def _try_connect(self, database_url: str) -> None:
        try:
            import psycopg

            self._conn = psycopg.connect(database_url, autocommit=True)
            with self._conn.cursor() as cur:
                cur.execute(_CREATE_AUDIT)
                for stmt in _MIGRATE_AUDIT:
                    cur.execute(stmt)
                cur.execute(_APPEND_ONLY_GUARD)
                cur.execute(_CREATE_RECOMMENDATION)
            self.db_connected = True
            logger.info("store connected to database", extra={"db_connected": True})
        except Exception as exc:  # pragma: no cover - exercised only with a real DB
            self._conn = None
            self.db_connected = False
            logger.warning(
                "store falling back to in-memory mode",
                extra={"db_connected": False, "error": str(exc)},
            )

    def set_event_sink(self, event_sink: Callable[[dict[str, Any]], None] | None) -> None:
        """Register (or clear) the advisory audit-appended hook."""
        self._event_sink = event_sink

    def _emit(self, event: dict[str, Any]) -> None:
        """Fire the advisory audit-appended hook, never breaking persistence."""
        sink = self._event_sink
        if sink is None:
            return
        try:
            sink(event)
        except Exception as exc:  # pragma: no cover - advisory hook is best-effort
            logger.warning("audit event sink failed", extra={"error": str(exc)})

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None
                    self.db_connected = False

    # -- audit ----------------------------------------------------------------

    def _db_chain_head(self) -> str:
        """Return the hash of the newest audit row (genesis when empty)."""
        with self._conn.cursor() as cur:  # pragma: no cover - real DB only
            cur.execute("SELECT hash FROM audit_event ORDER BY seq DESC LIMIT 1")
            row = cur.fetchone()
        if row and row[0]:
            return row[0]
        return audit_chain.GENESIS_HASH

    def audit(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        actor: str = "system",
        subject: str | None = None,
    ) -> dict[str, Any]:
        """Append a hash-chained audit event and return the stored record.

        The event is linked to the current chain head (``prev_hash``) and its
        own ``hash`` is derived from that link plus the event contents, making
        the trail tamper-evident. Appends only; there is deliberately no update
        or delete path for audit events.
        """
        event = {
            "id": str(uuid.uuid4()),
            "ts": _utcnow_iso(),
            "kind": kind,
            "actor": actor,
            "subject": subject,
            "payload": payload or {},
        }
        with self._lock:
            written_to_db = False
            if self.db_connected:
                try:
                    from psycopg.types.json import Jsonb

                    prev_hash = self._db_chain_head()
                    audit_chain.link_event(event, prev_hash)
                    with self._conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO audit_event "
                            "(id, ts, kind, actor, subject, payload, prev_hash, hash) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                            (
                                event["id"],
                                event["ts"],
                                event["kind"],
                                event["actor"],
                                event["subject"],
                                Jsonb(event["payload"]),
                                event["prev_hash"],
                                event["hash"],
                            ),
                        )
                    written_to_db = True
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning(
                        "audit write failed; mirroring to memory", extra={"error": str(exc)}
                    )
            if not written_to_db:
                audit_chain.link_event(event, self._chain_head)
                self._audit_mem.append(event)
                self._chain_head = event["hash"]
        # Emit outside the lock so the advisory hook (event-bus publish) can
        # never deadlock the store or block a persistence write.
        self._emit(event)
        return event

    def audit_chain_asc(self) -> list[dict[str, Any]]:
        """Return the full audit chain oldest-first (for verification)."""
        with self._lock:
            if self.db_connected:
                try:  # pragma: no cover - real DB only
                    with self._conn.cursor() as cur:
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
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("audit read failed; using memory", extra={"error": str(exc)})
            return list(self._audit_mem)

    def verify_chain(self) -> dict[str, Any]:
        """Verify the tamper-evident audit hash chain.

        Returns ``{"ok": True, ...}`` when intact, or ``{"ok": False,
        "broken_at": <event id>, ...}`` identifying the first event whose stored
        contents or link no longer match the chain.
        """
        return audit_chain.verify_chain(self.audit_chain_asc())

    def recent_audit(self, n: int = 100) -> list[dict[str, Any]]:
        """Return up to ``n`` most-recent audit events, newest first."""
        with self._lock:
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute(
                            "SELECT id, ts, kind, actor, subject, payload, prev_hash, hash "
                            "FROM audit_event ORDER BY seq DESC LIMIT %s",
                            (n,),
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
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("audit read failed; using memory", extra={"error": str(exc)})
            return list(reversed(self._audit_mem))[:n]

    # -- recommendations ------------------------------------------------------

    def save_recommendation(
        self,
        recommendation_id: str,
        card: dict[str, Any],
        *,
        facility_id: str | None = None,
        train_id: str | None = None,
        status: str = "pending",
    ) -> None:
        """Persist (or upsert) a recommendation card record."""
        with self._lock:
            if self.db_connected:
                try:
                    from psycopg.types.json import Jsonb

                    with self._conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO recommendation "
                            "(recommendation_id, facility_id, train_id, status, card) "
                            "VALUES (%s, %s, %s, %s, %s) "
                            "ON CONFLICT (recommendation_id) DO UPDATE SET "
                            "facility_id = EXCLUDED.facility_id, train_id = EXCLUDED.train_id, "
                            "status = EXCLUDED.status, card = EXCLUDED.card",
                            (recommendation_id, facility_id, train_id, status, Jsonb(card)),
                        )
                    return
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning(
                        "recommendation write failed; mirroring to memory",
                        extra={"error": str(exc)},
                    )
            self._rec_mem[recommendation_id] = {
                "recommendation_id": recommendation_id,
                "facility_id": facility_id,
                "train_id": train_id,
                "status": status,
                "card": card,
            }

    def set_status(self, recommendation_id: str, status: str) -> None:
        with self._lock:
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute(
                            "UPDATE recommendation SET status = %s WHERE recommendation_id = %s",
                            (status, recommendation_id),
                        )
                    return
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("status update failed; using memory", extra={"error": str(exc)})
            rec = self._rec_mem.get(recommendation_id)
            if rec is not None:
                rec["status"] = status

    def reset(self) -> None:
        """Clear the in-memory mirrors and truncate DB tables (advisory data only)."""
        with self._lock:
            self._audit_mem.clear()
            self._rec_mem.clear()
            self._chain_head = audit_chain.GENESIS_HASH
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute("TRUNCATE audit_event")
                        cur.execute("TRUNCATE recommendation")
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("reset truncate failed", extra={"error": str(exc)})
