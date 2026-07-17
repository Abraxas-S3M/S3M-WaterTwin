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

# Operator-feedback capture: one row per confirm/dismiss decision an operator
# records against a condition-intelligence alert. This is the ground-truth
# signal the condition framework's back-test and calibration harnesses learn
# from. Append-only in spirit (each decision is a new row, keyed by feedback_id)
# and, like everything else here, advisory only -- it never writes to control.
_CREATE_FEEDBACK = """
CREATE TABLE IF NOT EXISTS operator_feedback (
    feedback_id TEXT PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    alert_id TEXT NOT NULL,
    recommendation_id TEXT,
    asset_id TEXT,
    model_id TEXT,
    decision TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'operator',
    note TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""

#: The operator decisions the feedback store accepts on an alert.
FEEDBACK_DECISIONS: frozenset[str] = frozenset({"confirm", "dismiss"})
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
# Add tenant scoping to recommendation records created before multi-tenancy and
# backfill legacy rows into the default tenant/facility (parity migration).
_MIGRATE_RECOMMENDATION = (
    "ALTER TABLE recommendation ADD COLUMN IF NOT EXISTS tenant_id TEXT",
    "UPDATE recommendation SET tenant_id = %(tenant)s WHERE tenant_id IS NULL",
    "UPDATE recommendation SET facility_id = %(facility)s WHERE facility_id IS NULL",
)
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
        self._feedback_mem: list[dict[str, Any]] = []
        # Config versions, keyed by version_id, in insertion order.
        self._config_mem: dict[str, dict[str, Any]] = {}
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

            scope_params = {"tenant": _default_tenant(), "facility": _default_facility()}
            self._conn = psycopg.connect(database_url, autocommit=True)
            with self._conn.cursor() as cur:
                cur.execute(_CREATE_AUDIT)
                for stmt in _MIGRATE_AUDIT:
                    cur.execute(stmt, scope_params)
                cur.execute(_APPEND_ONLY_GUARD)
                cur.execute(_CREATE_RECOMMENDATION)
                cur.execute(_CREATE_FEEDBACK)
                cur.execute(_CREATE_CONFIG_VERSION)
                for stmt in _MIGRATE_RECOMMENDATION:
                    cur.execute(stmt, scope_params)
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
            written_to_db = False
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

    # -- operator feedback ----------------------------------------------------

    def record_feedback(
        self,
        alert_id: str,
        decision: str,
        *,
        recommendation_id: str | None = None,
        asset_id: str | None = None,
        model_id: str | None = None,
        actor: str = "operator",
        note: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an operator confirm/dismiss decision on a condition alert.

        This is the ground-truth capture the condition-intelligence framework's
        back-test and calibration harnesses consume. It is advisory metadata
        only and never writes to any control system. Returns the stored record.

        Raises:
            ValueError: If ``decision`` is not one of :data:`FEEDBACK_DECISIONS`.
        """
        norm = decision.lower().strip()
        if norm not in FEEDBACK_DECISIONS:
            raise ValueError(
                f"decision must be one of {sorted(FEEDBACK_DECISIONS)}; got {decision!r}."
            )
        record = {
            "feedback_id": str(uuid.uuid4()),
            "ts": _utcnow_iso(),
            "alert_id": alert_id,
            "recommendation_id": recommendation_id,
            "asset_id": asset_id,
            "model_id": model_id,
            "decision": norm,
            "actor": actor,
            "note": note,
            "payload": payload or {},
        }
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

                    with self._conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO operator_feedback "
                            "(feedback_id, ts, alert_id, recommendation_id, asset_id, "
                            "model_id, decision, actor, note, payload) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                            (
                                record["feedback_id"],
                                record["ts"],
                                record["alert_id"],
                                record["recommendation_id"],
                                record["asset_id"],
                                record["model_id"],
                                record["decision"],
                                record["actor"],
                                record["note"],
                                Jsonb(record["payload"]),
                            ),
                        )
                    return record
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning(
                        "feedback write failed; mirroring to memory",
                        extra={"error": str(exc)},
                    )
            self._feedback_mem.append(record)
        return record

    def feedback_for(self, alert_id: str) -> list[dict[str, Any]]:
        """Return every recorded feedback decision for one alert (oldest first)."""
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
                            "SELECT feedback_id, ts, alert_id, recommendation_id, asset_id, "
                            "model_id, decision, actor, note, payload "
                            "FROM operator_feedback WHERE alert_id = %s ORDER BY ts ASC",
                            (alert_id,),
                        )
                        rows = cur.fetchall()
                    return [self._feedback_row(r) for r in rows]
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("feedback read failed; using memory", extra={"error": str(exc)})
            return [f for f in self._feedback_mem if f["alert_id"] == alert_id]

    def recent_feedback(self, n: int = 100) -> list[dict[str, Any]]:
        """Return up to ``n`` most-recent feedback decisions, newest first."""
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
                            "SELECT feedback_id, ts, alert_id, recommendation_id, asset_id, "
                            "model_id, decision, actor, note, payload "
                            "FROM operator_feedback ORDER BY ts DESC LIMIT %s",
                            (n,),
                        )
                        rows = cur.fetchall()
                    return [self._feedback_row(r) for r in rows]
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("feedback read failed; using memory", extra={"error": str(exc)})
            return list(reversed(self._feedback_mem))[:n]

    @staticmethod
    def _feedback_row(r: Any) -> dict[str, Any]:  # pragma: no cover - real DB only
        return {
            "feedback_id": str(r[0]),
            "ts": r[1].isoformat() if hasattr(r[1], "isoformat") else r[1],
            "alert_id": r[2],
            "recommendation_id": r[3],
            "asset_id": r[4],
            "model_id": r[5],
            "decision": r[6],
            "actor": r[7],
            "note": r[8],
            "payload": r[9],
        }
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
            self._feedback_mem.clear()
            self._config_mem.clear()
            self._telemetry_mem.clear()
            self._batch_mem.clear()
            self._chain_head = audit_chain.GENESIS_HASH
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute("TRUNCATE audit_event")
                        cur.execute("TRUNCATE recommendation")
                        cur.execute("TRUNCATE operator_feedback")
                        cur.execute("TRUNCATE config_version")
                        cur.execute("TRUNCATE telemetry")
                        cur.execute("TRUNCATE telemetry_batch")
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("reset truncate failed", extra={"error": str(exc)})
