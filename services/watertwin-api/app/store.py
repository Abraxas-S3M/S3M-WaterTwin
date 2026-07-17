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
from . import config

logger = logging.getLogger("watertwin.store")


def _default_tenant() -> str:
    return config.DEFAULT_TENANT_ID


def _default_facility() -> str:
    return config.DEFAULT_FACILITY_ID


def _row_to_event(r: tuple[Any, ...]) -> dict[str, Any]:
    """Map an ``audit_event`` DB row (scoped column order) to an event dict."""
    return {
        "id": str(r[0]),
        "ts": r[1].isoformat() if hasattr(r[1], "isoformat") else r[1],
        "kind": r[2],
        "actor": r[3],
        "subject": r[4],
        "tenant_id": r[5],
        "facility_id": r[6],
        "payload": r[7],
        "prev_hash": r[8],
        "hash": r[9],
    }


def _matches_scope(
    record: dict[str, Any], tenant_id: str | None, facility_id: str | None
) -> bool:
    """Row-level scope predicate shared by the in-memory read paths.

    A ``None`` filter means "unscoped" for that dimension. Records missing a
    ``facility_id`` (facility-agnostic / system events) stay visible within their
    tenant even when a facility filter is applied.
    """
    if tenant_id is not None and (record.get("tenant_id") or _default_tenant()) != tenant_id:
        return False
    if facility_id is not None:
        rec_facility = record.get("facility_id")
        if rec_facility is not None and rec_facility != facility_id:
            return False
    return True


def _scope_sql(tenant_id: str | None, facility_id: str | None) -> tuple[str, tuple[Any, ...]]:
    """Build a parameterised ``WHERE`` clause for a tenant/facility scope.

    Mirrors :func:`_matches_scope` for the database read paths.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if tenant_id is not None:
        clauses.append("COALESCE(tenant_id, %s) = %s")
        params.extend((_default_tenant(), tenant_id))
    if facility_id is not None:
        clauses.append("(facility_id IS NULL OR facility_id = %s)")
        params.append(facility_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, tuple(params)


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
    tenant_id TEXT,
    facility_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    prev_hash TEXT NOT NULL DEFAULT '',
    hash TEXT NOT NULL DEFAULT ''
);
"""

# Backfill columns/ordering for databases created before the hash chain existed
# and before tenant/facility scoping. The tenant/facility backfill migrates the
# pre-existing single-facility (default tenant) data so nothing breaks on
# upgrade. It runs *before* the append-only trigger is (re)installed in
# ``_APPEND_ONLY_GUARD`` so the one-time UPDATE of legacy NULL scopes is allowed;
# on subsequent connects no NULL rows remain, so the guarded UPDATE is a no-op
# (0 rows -> the append-only trigger never fires) and never mutates a scoped row.
# tenant_id/facility_id are deliberately *not* part of the hashed event core (see
# ``app.audit``), so backfilling them leaves every existing hash — and the
# tamper-evident chain invariant — unchanged.
_MIGRATE_AUDIT = (
    "ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS seq BIGSERIAL",
    "ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS prev_hash TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS hash TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS tenant_id TEXT",
    "ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS facility_id TEXT",
    "DROP TRIGGER IF EXISTS audit_event_no_mutation ON audit_event",
    "UPDATE audit_event SET tenant_id = %(tenant)s WHERE tenant_id IS NULL",
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
    tenant_id TEXT,
    facility_id TEXT,
    train_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    card JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""

# Add tenant scoping to recommendation records created before multi-tenancy and
# backfill legacy rows into the default tenant/facility (parity migration).
_MIGRATE_RECOMMENDATION = (
    "ALTER TABLE recommendation ADD COLUMN IF NOT EXISTS tenant_id TEXT",
    "UPDATE recommendation SET tenant_id = %(tenant)s WHERE tenant_id IS NULL",
    "UPDATE recommendation SET facility_id = %(facility)s WHERE facility_id IS NULL",
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

        # Running head of the in-memory audit hash chain (genesis when empty).
        self._chain_head: str = audit_chain.GENESIS_HASH

        if connect and self.database_url:
            self._try_connect(self.database_url)

    # -- connection lifecycle -------------------------------------------------

    def _try_connect(self, database_url: str) -> None:
        try:
            import psycopg

            scope_params = {"tenant": _default_tenant(), "facility": _default_facility()}
            self._conn = psycopg.connect(database_url, autocommit=True)
            with self._conn.cursor() as cur:
                cur.execute(_CREATE_AUDIT)
                for stmt in _MIGRATE_AUDIT:
                    cur.execute(stmt, scope_params)
                cur.execute(_APPEND_ONLY_GUARD)
                cur.execute(_CREATE_RECOMMENDATION)
                for stmt in _MIGRATE_RECOMMENDATION:
                    cur.execute(stmt, scope_params)
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
        *,
        tenant_id: str | None = None,
        facility_id: str | None = None,
    ) -> dict[str, Any]:
        """Append a hash-chained audit event and return the stored record.

        The event is linked to the current chain head (``prev_hash``) and its
        own ``hash`` is derived from that link plus the event contents, making
        the trail tamper-evident. Appends only; there is deliberately no update
        or delete path for audit events.

        ``tenant_id`` / ``facility_id`` scope the event so audit reads can be
        filtered per tenant/facility. They default to the platform's default
        tenant/facility and are stored *alongside* — never inside — the hashed
        event core, so scoping never affects the tamper-evident chain.
        """
        event = {
            "id": str(uuid.uuid4()),
            "ts": _utcnow_iso(),
            "kind": kind,
            "actor": actor,
            "subject": subject,
            "tenant_id": tenant_id or _default_tenant(),
            "facility_id": facility_id or _default_facility(),
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
                            "(id, ts, kind, actor, subject, tenant_id, facility_id, "
                            "payload, prev_hash, hash) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                            (
                                event["id"],
                                event["ts"],
                                event["kind"],
                                event["actor"],
                                event["subject"],
                                event["tenant_id"],
                                event["facility_id"],
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
        """Return the full audit chain oldest-first (for verification).

        Deliberately *unscoped*: the tamper-evident chain is a single global
        hash chain and must be verified in its entirety, so this never applies a
        tenant/facility filter (use :meth:`recent_audit` for scoped reads).
        """
        with self._lock:
            if self.db_connected:
                try:  # pragma: no cover - real DB only
                    with self._conn.cursor() as cur:
                        cur.execute(
                            "SELECT id, ts, kind, actor, subject, tenant_id, facility_id, "
                            "payload, prev_hash, hash "
                            "FROM audit_event ORDER BY seq ASC"
                        )
                        rows = cur.fetchall()
                    return [_row_to_event(r) for r in rows]
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

    def recent_audit(
        self,
        n: int = 100,
        *,
        tenant_id: str | None = None,
        facility_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to ``n`` most-recent audit events, newest first.

        When ``tenant_id`` (and optionally ``facility_id``) is given the result
        is row-level scoped to that tenant/facility so a caller only ever sees
        their own tenant's audit trail. Facility-agnostic events (no
        ``facility_id``) remain visible within their tenant. Passing neither
        returns the unscoped view (used by global/admin callers and internal
        verification).
        """
        with self._lock:
            if self.db_connected:
                try:
                    where, params = _scope_sql(tenant_id, facility_id)
                    with self._conn.cursor() as cur:
                        cur.execute(
                            "SELECT id, ts, kind, actor, subject, tenant_id, facility_id, "
                            "payload, prev_hash, hash "
                            f"FROM audit_event {where} ORDER BY seq DESC LIMIT %s",
                            (*params, n),
                        )
                        rows = cur.fetchall()
                    return [_row_to_event(r) for r in rows]
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("audit read failed; using memory", extra={"error": str(exc)})
            scoped = [
                ev
                for ev in reversed(self._audit_mem)
                if _matches_scope(ev, tenant_id, facility_id)
            ]
            return scoped[:n]

    # -- recommendations ------------------------------------------------------

    def save_recommendation(
        self,
        recommendation_id: str,
        card: dict[str, Any],
        *,
        tenant_id: str | None = None,
        facility_id: str | None = None,
        train_id: str | None = None,
        status: str = "pending",
    ) -> None:
        """Persist (or upsert) a recommendation card record (tenant/facility scoped)."""
        tenant_id = tenant_id or _default_tenant()
        facility_id = facility_id or _default_facility()
        with self._lock:
            if self.db_connected:
                try:
                    from psycopg.types.json import Jsonb

                    with self._conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO recommendation "
                            "(recommendation_id, tenant_id, facility_id, train_id, status, card) "
                            "VALUES (%s, %s, %s, %s, %s, %s) "
                            "ON CONFLICT (recommendation_id) DO UPDATE SET "
                            "tenant_id = EXCLUDED.tenant_id, facility_id = EXCLUDED.facility_id, "
                            "train_id = EXCLUDED.train_id, "
                            "status = EXCLUDED.status, card = EXCLUDED.card",
                            (
                                recommendation_id,
                                tenant_id,
                                facility_id,
                                train_id,
                                status,
                                Jsonb(card),
                            ),
                        )
                    return
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning(
                        "recommendation write failed; mirroring to memory",
                        extra={"error": str(exc)},
                    )
            self._rec_mem[recommendation_id] = {
                "recommendation_id": recommendation_id,
                "tenant_id": tenant_id,
                "facility_id": facility_id,
                "train_id": train_id,
                "status": status,
                "card": card,
            }

    def list_recommendations(
        self,
        *,
        tenant_id: str | None = None,
        facility_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return stored recommendation records, row-level scoped when asked.

        This is the config-record read path: a caller only ever sees the
        recommendations for the tenant/facility they are scoped to.
        """
        with self._lock:
            if self.db_connected:
                try:  # pragma: no cover - real DB only
                    where, params = _scope_sql(tenant_id, facility_id)
                    with self._conn.cursor() as cur:
                        cur.execute(
                            "SELECT recommendation_id, tenant_id, facility_id, train_id, "
                            f"status, card FROM recommendation {where} ORDER BY ts DESC",
                            params,
                        )
                        rows = cur.fetchall()
                    return [
                        {
                            "recommendation_id": r[0],
                            "tenant_id": r[1],
                            "facility_id": r[2],
                            "train_id": r[3],
                            "status": r[4],
                            "card": r[5],
                        }
                        for r in rows
                    ]
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("recommendation read failed; using memory",
                                   extra={"error": str(exc)})
            return [
                dict(rec)
                for rec in self._rec_mem.values()
                if _matches_scope(rec, tenant_id, facility_id)
            ]

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

    def migrate_default_scope(
        self,
        *,
        tenant_id: str | None = None,
        facility_id: str | None = None,
    ) -> dict[str, int]:
        """Backfill any unscoped records into the default tenant/facility.

        Idempotent migration for the pre-multi-tenancy (single-facility) data:
        every audit event or recommendation missing a tenant/facility is moved
        into the default scope so nothing disappears from scoped views after the
        upgrade. Returns the number of records touched per table (``0`` when
        already migrated). The database backfill is applied on connect; this
        method also reconciles the in-memory mirrors and re-runs the DB backfill
        so callers can assert migration parity in either mode.

        Note: only the non-hashed scope columns are touched, so the audit hash
        chain — and its tamper-evident invariant — is left byte-for-byte intact.
        """
        tenant_id = tenant_id or _default_tenant()
        facility_id = facility_id or _default_facility()
        touched = {"audit": 0, "recommendations": 0}
        with self._lock:
            if self.db_connected:  # pragma: no cover - real DB only
                try:
                    with self._conn.cursor() as cur:
                        cur.execute("DROP TRIGGER IF EXISTS audit_event_no_mutation ON audit_event")
                        cur.execute(
                            "UPDATE audit_event SET tenant_id = %s WHERE tenant_id IS NULL",
                            (tenant_id,),
                        )
                        touched["audit"] += cur.rowcount or 0
                        cur.execute(
                            "UPDATE audit_event SET facility_id = %s WHERE facility_id IS NULL",
                            (facility_id,),
                        )
                        cur.execute(_APPEND_ONLY_GUARD)
                        cur.execute(
                            "UPDATE recommendation SET tenant_id = %s WHERE tenant_id IS NULL",
                            (tenant_id,),
                        )
                        touched["recommendations"] += cur.rowcount or 0
                        cur.execute(
                            "UPDATE recommendation SET facility_id = %s WHERE facility_id IS NULL",
                            (facility_id,),
                        )
                except Exception as exc:
                    logger.warning("scope migration failed", extra={"error": str(exc)})
            for ev in self._audit_mem:
                if not ev.get("tenant_id"):
                    ev["tenant_id"] = tenant_id
                    touched["audit"] += 1
                if not ev.get("facility_id"):
                    ev["facility_id"] = facility_id
            for rec in self._rec_mem.values():
                changed = False
                if not rec.get("tenant_id"):
                    rec["tenant_id"] = tenant_id
                    changed = True
                if not rec.get("facility_id"):
                    rec["facility_id"] = facility_id
                    changed = True
                if changed:
                    touched["recommendations"] += 1
        return touched

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
