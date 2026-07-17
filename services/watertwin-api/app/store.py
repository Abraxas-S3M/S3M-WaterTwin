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

import hashlib
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

# Telemetry hypertable (created by infrastructure/database/init.sql; ensured here
# idempotently so the ingest path also works against a plain Postgres). One row
# per (asset, metric, time) reading forwarded by an edge gateway. This holds
# advisory synthetic/simulated (or provenance-tagged) readings only -- never a
# control-write path.
_CREATE_TELEMETRY = """
CREATE TABLE IF NOT EXISTS telemetry (
    time        TIMESTAMPTZ      NOT NULL DEFAULT now(),
    asset_id    TEXT             NOT NULL,
    metric      TEXT             NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    unit        TEXT,
    facility_id TEXT,
    train_id    TEXT,
    provenance  TEXT             NOT NULL DEFAULT 'synthetic',
    quality     TEXT             NOT NULL DEFAULT 'good'
);
"""

# Idempotency ledger for telemetry ingest. Each forwarded batch is recorded by
# its stable ``batch_id`` (the edge gateway's store-and-forward key). A second
# delivery of the same batch_id is a no-op, so an edge gateway that replays its
# on-disk spool after a crash/restart never double-writes telemetry or the audit
# trail -- this is what makes store-and-forward recovery lossless *and*
# duplicate-free. ``digest`` binds the recorded batch to its content.
_CREATE_TELEMETRY_BATCH = """
CREATE TABLE IF NOT EXISTS telemetry_batch (
    batch_id      TEXT        PRIMARY KEY,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    reading_count INTEGER     NOT NULL DEFAULT 0,
    digest        TEXT        NOT NULL DEFAULT '',
    source        TEXT
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
        self._telemetry_mem: list[dict[str, Any]] = []
        # Idempotency ledger: batch_id -> {"count", "digest", "source"}.
        self._batch_mem: dict[str, dict[str, Any]] = {}

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
                cur.execute(_CREATE_TELEMETRY)
                cur.execute(_CREATE_TELEMETRY_BATCH)
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

    def audit_length(self) -> int:
        """Return the number of events in the audit chain (cheap COUNT/len)."""
        with self._lock:
            if self.db_connected:
                try:  # pragma: no cover - real DB only
                    with self._conn.cursor() as cur:
                        cur.execute("SELECT count(*) FROM audit_event")
                        row = cur.fetchone()
                    return int(row[0]) if row else 0
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("audit count failed; using memory", extra={"error": str(exc)})
            return len(self._audit_mem)

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

    # -- telemetry ingest (store-and-forward destination) ---------------------

    @staticmethod
    def _batch_digest(readings: list[dict[str, Any]]) -> str:
        """Content digest of a batch, bound into its audit event.

        Uses the same canonical (sorted-key, compact) JSON encoding as the audit
        chain so the same readings always yield the same digest.
        """
        return hashlib.sha256(audit_chain.canonical(readings).encode("utf-8")).hexdigest()

    def ingest_telemetry(
        self,
        batch_id: str,
        readings: list[dict[str, Any]],
        *,
        actor: str = "edge-gateway",
        source: str | None = None,
    ) -> dict[str, Any]:
        """Idempotently ingest a batch of telemetry readings.

        Readings are appended to the ``telemetry`` store and a single
        ``telemetry.ingested`` event is appended to the tamper-evident audit
        chain (its payload binds the ``batch_id``, count and content digest).

        Ingest is idempotent on ``batch_id``: a repeat delivery of an already
        recorded batch is a no-op that returns ``{"duplicate": True}`` without
        re-inserting readings or appending a second audit event. This is what
        lets an edge gateway replay its durable spool after a crash with no data
        loss *and* no duplication, while the audit chain stays valid.

        This is a telemetry *read into* the platform, not a control write.
        """
        digest = self._batch_digest(readings)
        with self._lock:
            if self.db_connected:
                try:  # pragma: no cover - real DB only
                    return self._ingest_telemetry_db(
                        batch_id, readings, digest, actor=actor, source=source
                    )
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning(
                        "telemetry ingest failed; mirroring to memory",
                        extra={"error": str(exc)},
                    )
            return self._ingest_telemetry_mem(
                batch_id, readings, digest, actor=actor, source=source
            )

    def _ingest_telemetry_mem(
        self,
        batch_id: str,
        readings: list[dict[str, Any]],
        digest: str,
        *,
        actor: str,
        source: str | None,
    ) -> dict[str, Any]:
        prior = self._batch_mem.get(batch_id)
        if prior is not None:
            return {
                "batch_id": batch_id,
                "duplicate": True,
                "accepted": 0,
                "reading_count": prior["count"],
                "audit_id": None,
            }
        self._telemetry_mem.extend(readings)
        self._batch_mem[batch_id] = {
            "count": len(readings),
            "digest": digest,
            "source": source,
        }
        event = self.audit(
            "telemetry.ingested",
            payload={
                "batch_id": batch_id,
                "reading_count": len(readings),
                "digest": digest,
                "source": source,
            },
            actor=actor,
            subject=batch_id,
        )
        return {
            "batch_id": batch_id,
            "duplicate": False,
            "accepted": len(readings),
            "reading_count": len(readings),
            "audit_id": event["id"],
        }

    def _ingest_telemetry_db(  # pragma: no cover - exercised only with a real DB
        self,
        batch_id: str,
        readings: list[dict[str, Any]],
        digest: str,
        *,
        actor: str,
        source: str | None,
    ) -> dict[str, Any]:
        from psycopg.types.json import Jsonb

        with self._conn.cursor() as cur:
            cur.execute("SELECT reading_count FROM telemetry_batch WHERE batch_id = %s", (batch_id,))
            existing = cur.fetchone()
        if existing is not None:
            return {
                "batch_id": batch_id,
                "duplicate": True,
                "accepted": 0,
                "reading_count": existing[0],
                "audit_id": None,
            }

        event = {
            "id": str(uuid.uuid4()),
            "ts": _utcnow_iso(),
            "kind": "telemetry.ingested",
            "actor": actor,
            "subject": batch_id,
            "payload": {
                "batch_id": batch_id,
                "reading_count": len(readings),
                "digest": digest,
                "source": source,
            },
        }

        # Telemetry rows + idempotency marker + audit event committed atomically,
        # so a crash mid-ingest leaves the batch either fully recorded or not at
        # all (a partial batch would let a replay double-count).
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                if readings:
                    cur.executemany(
                        "INSERT INTO telemetry "
                        "(time, asset_id, metric, value, unit, provenance, quality) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        [
                            (
                                r.get("timestamp"),
                                r.get("asset_id"),
                                r.get("metric"),
                                r.get("value"),
                                r.get("unit"),
                                r.get("provenance", "synthetic"),
                                r.get("quality") or "good",
                            )
                            for r in readings
                        ],
                    )
                cur.execute(
                    "INSERT INTO telemetry_batch (batch_id, reading_count, digest, source) "
                    "VALUES (%s, %s, %s, %s)",
                    (batch_id, len(readings), digest, source),
                )
                prev_hash = self._db_chain_head()
                audit_chain.link_event(event, prev_hash)
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
        return {
            "batch_id": batch_id,
            "duplicate": False,
            "accepted": len(readings),
            "reading_count": len(readings),
            "audit_id": event["id"],
        }

    def telemetry_stats(self) -> dict[str, Any]:
        """Return ingest counters: distinct batches and total readings ingested."""
        with self._lock:
            if self.db_connected:
                try:  # pragma: no cover - real DB only
                    with self._conn.cursor() as cur:
                        cur.execute(
                            "SELECT count(*), COALESCE(sum(reading_count), 0) FROM telemetry_batch"
                        )
                        row = cur.fetchone()
                    return {"batches": int(row[0]), "readings": int(row[1])}
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("telemetry stats read failed; using memory", extra={"error": str(exc)})
            return {"batches": len(self._batch_mem), "readings": len(self._telemetry_mem)}

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
            self._telemetry_mem.clear()
            self._batch_mem.clear()
            self._chain_head = audit_chain.GENESIS_HASH
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute("TRUNCATE audit_event")
                        cur.execute("TRUNCATE recommendation")
                        cur.execute("TRUNCATE telemetry")
                        cur.execute("TRUNCATE telemetry_batch")
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("reset truncate failed", extra={"error": str(exc)})
