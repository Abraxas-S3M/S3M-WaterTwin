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

logger = logging.getLogger("watertwin.store")


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


_CREATE_AUDIT = """
CREATE TABLE IF NOT EXISTS audit_event (
    id UUID PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    subject TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
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

    def __init__(self, database_url: str | None = None, *, connect: bool = True) -> None:
        self.database_url = database_url or None
        self.db_connected = False
        self._conn: Any = None
        self._lock = threading.RLock()

        # In-memory mirrors used whenever the database is unavailable.
        self._audit_mem: list[dict[str, Any]] = []
        self._rec_mem: dict[str, dict[str, Any]] = {}

        if connect and self.database_url:
            self._try_connect(self.database_url)

    # -- connection lifecycle -------------------------------------------------

    def _try_connect(self, database_url: str) -> None:
        try:
            import psycopg

            self._conn = psycopg.connect(database_url, autocommit=True)
            with self._conn.cursor() as cur:
                cur.execute(_CREATE_AUDIT)
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

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None
                    self.db_connected = False

    # -- audit ----------------------------------------------------------------

    def audit(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        actor: str = "system",
        subject: str | None = None,
    ) -> dict[str, Any]:
        """Record an audit event and return the stored record."""
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

                    with self._conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO audit_event (id, ts, kind, actor, subject, payload) "
                            "VALUES (%s, %s, %s, %s, %s, %s)",
                            (
                                event["id"],
                                event["ts"],
                                event["kind"],
                                event["actor"],
                                event["subject"],
                                Jsonb(event["payload"]),
                            ),
                        )
                    return event
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning(
                        "audit write failed; mirroring to memory", extra={"error": str(exc)}
                    )
            self._audit_mem.append(event)
        return event

    def recent_audit(self, n: int = 100) -> list[dict[str, Any]]:
        """Return up to ``n`` most-recent audit events, newest first."""
        with self._lock:
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute(
                            "SELECT id, ts, kind, actor, subject, payload FROM audit_event "
                            "ORDER BY ts DESC LIMIT %s",
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
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute("TRUNCATE audit_event")
                        cur.execute("TRUNCATE recommendation")
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("reset truncate failed", extra={"error": str(exc)})
