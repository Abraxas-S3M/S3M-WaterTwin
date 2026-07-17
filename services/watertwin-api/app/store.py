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

# Versioned, approval-gated customer configuration. Each row is one immutable
# *version* of a logical configuration (``entity_type`` + ``config_id``). The
# lifecycle (draft -> submitted -> approved -> active -> superseded) is enforced
# by the configuration service; a version's ``payload`` is frozen once it leaves
# ``draft``. State changes are recorded in the tamper-evident ``audit_event``
# chain. Nothing here is a control-write path -- configuration is declarative.
_CREATE_CONFIG_VERSION = """
CREATE TABLE IF NOT EXISTS config_version (
    version_id UUID PRIMARY KEY,
    entity_type TEXT NOT NULL,
    config_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_by TEXT,
    submitted_at TIMESTAMPTZ,
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    activated_at TIMESTAMPTZ,
    superseded_by UUID,
    UNIQUE (entity_type, config_id, version)
);
CREATE INDEX IF NOT EXISTS config_version_lookup_idx
    ON config_version (entity_type, config_id, version DESC);
CREATE INDEX IF NOT EXISTS config_version_status_idx
    ON config_version (entity_type, status);
"""

# Columns persisted for a config version, in a stable order used by both the
# DB and in-memory paths.
_CONFIG_COLUMNS = (
    "version_id",
    "entity_type",
    "config_id",
    "version",
    "status",
    "payload",
    "created_by",
    "created_at",
    "updated_at",
    "submitted_by",
    "submitted_at",
    "approved_by",
    "approved_at",
    "activated_at",
    "superseded_by",
)


class Store:
    """Audit + recommendation persistence with graceful in-memory fallback."""

    def __init__(self, database_url: str | None = None, *, connect: bool = True) -> None:
        self.database_url = database_url or None
        self.db_connected = False
        self._conn: Any = None
        self._lock = threading.RLock()

        # In-memory mirrors used whenever the database is unavailable.
        self._audit_mem: list[dict[str, Any]] = []
        self._rec_mem: dict[str, dict[str, Any]] = {}
        # Config versions, keyed by version_id, in insertion order.
        self._config_mem: dict[str, dict[str, Any]] = {}

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
                cur.execute(_CREATE_CONFIG_VERSION)
            self.db_connected = True
            logger.info("store connected to database", extra={"db_connected": True})
        except Exception as exc:  # pragma: no cover - exercised only with a real DB
            self._conn = None
            self.db_connected = False
            logger.warning(
                "store falling back to in-memory mode",
                extra={"db_connected": False, "error": str(exc)},
            )

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
                    return event
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning(
                        "audit write failed; mirroring to memory", extra={"error": str(exc)}
                    )
            audit_chain.link_event(event, self._chain_head)
            self._audit_mem.append(event)
            self._chain_head = event["hash"]
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

    # -- configuration versions ----------------------------------------------

    @staticmethod
    def _config_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        record = dict(zip(_CONFIG_COLUMNS, row))
        record["version_id"] = str(record["version_id"])
        if record.get("superseded_by") is not None:
            record["superseded_by"] = str(record["superseded_by"])
        for ts_field in ("created_at", "updated_at", "submitted_at", "approved_at", "activated_at"):
            val = record.get(ts_field)
            if hasattr(val, "isoformat"):
                record[ts_field] = val.isoformat()
        return record

    def save_config_version(self, record: dict[str, Any]) -> dict[str, Any]:
        """Insert a new immutable configuration version row."""
        row = {col: record.get(col) for col in _CONFIG_COLUMNS}
        with self._lock:
            if self.db_connected:
                try:
                    from psycopg.types.json import Jsonb

                    values = dict(row)
                    values["payload"] = Jsonb(values.get("payload") or {})
                    placeholders = ", ".join(["%s"] * len(_CONFIG_COLUMNS))
                    with self._conn.cursor() as cur:
                        cur.execute(
                            f"INSERT INTO config_version ({', '.join(_CONFIG_COLUMNS)}) "
                            f"VALUES ({placeholders})",
                            tuple(values[col] for col in _CONFIG_COLUMNS),
                        )
                    return dict(row)
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning(
                        "config write failed; mirroring to memory", extra={"error": str(exc)}
                    )
            self._config_mem[str(row["version_id"])] = dict(row)
        return dict(row)

    def update_config_version(self, version_id: str, fields: dict[str, Any]) -> None:
        """Update mutable lifecycle/metadata fields of a config version.

        Only used by the configuration service to advance a version's status and
        stamp the actor/timestamps; a version's ``payload`` is only mutated while
        it is still a ``draft``.
        """
        with self._lock:
            if self.db_connected:
                try:
                    from psycopg.types.json import Jsonb

                    sets = []
                    params: list[Any] = []
                    for key, value in fields.items():
                        sets.append(f"{key} = %s")
                        params.append(Jsonb(value) if key == "payload" else value)
                    params.append(version_id)
                    with self._conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE config_version SET {', '.join(sets)} WHERE version_id = %s",
                            tuple(params),
                        )
                    return
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("config update failed; using memory", extra={"error": str(exc)})
            rec = self._config_mem.get(version_id)
            if rec is not None:
                rec.update(fields)

    def get_config_version(self, version_id: str) -> dict[str, Any] | None:
        """Return a single config version by its version id."""
        with self._lock:
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute(
                            f"SELECT {', '.join(_CONFIG_COLUMNS)} FROM config_version "
                            "WHERE version_id = %s",
                            (version_id,),
                        )
                        row = cur.fetchone()
                    return self._config_row_to_dict(row) if row else None
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("config read failed; using memory", extra={"error": str(exc)})
            rec = self._config_mem.get(version_id)
            return dict(rec) if rec else None

    def list_config_versions(
        self, entity_type: str, config_id: str
    ) -> list[dict[str, Any]]:
        """Return all versions of a logical config, oldest-first."""
        with self._lock:
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute(
                            f"SELECT {', '.join(_CONFIG_COLUMNS)} FROM config_version "
                            "WHERE entity_type = %s AND config_id = %s ORDER BY version ASC",
                            (entity_type, config_id),
                        )
                        rows = cur.fetchall()
                    return [self._config_row_to_dict(r) for r in rows]
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("config read failed; using memory", extra={"error": str(exc)})
            versions = [
                dict(r)
                for r in self._config_mem.values()
                if r["entity_type"] == entity_type and r["config_id"] == config_id
            ]
            return sorted(versions, key=lambda r: r["version"])

    def list_config_active(self, entity_type: str) -> list[dict[str, Any]]:
        """Return the active version of every logical config of an entity type."""
        with self._lock:
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute(
                            f"SELECT {', '.join(_CONFIG_COLUMNS)} FROM config_version "
                            "WHERE entity_type = %s AND status = 'active' ORDER BY config_id ASC",
                            (entity_type,),
                        )
                        rows = cur.fetchall()
                    return [self._config_row_to_dict(r) for r in rows]
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("config read failed; using memory", extra={"error": str(exc)})
            active = [
                dict(r)
                for r in self._config_mem.values()
                if r["entity_type"] == entity_type and r["status"] == "active"
            ]
            return sorted(active, key=lambda r: r["config_id"])

    def reset(self) -> None:
        """Clear the in-memory mirrors and truncate DB tables (advisory data only)."""
        with self._lock:
            self._audit_mem.clear()
            self._rec_mem.clear()
            self._config_mem.clear()
            self._chain_head = audit_chain.GENESIS_HASH
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute("TRUNCATE audit_event")
                        cur.execute("TRUNCATE recommendation")
                        cur.execute("TRUNCATE config_version")
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("reset truncate failed", extra={"error": str(exc)})
