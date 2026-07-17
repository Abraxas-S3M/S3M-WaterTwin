"""Durable audit / recommendation store with an in-memory fallback.

The :class:`Store` prefers a Postgres/TimescaleDB backend (via psycopg 3) but is
designed never to crash when the database is absent or unreachable. When no working
connection is available it operates purely in memory and reports
``db_connected=False``. This keeps local development and the graceful-degradation
path (see :mod:`watertwin.s3m_connector`) fully functional without infrastructure.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from .schemas import ApprovalStatus, RecommendationCard

logger = logging.getLogger("watertwin.store")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _status_value(status: Any) -> str:
    return status.value if isinstance(status, ApprovalStatus) else str(status)


_CREATE_AUDIT = """
CREATE TABLE IF NOT EXISTS audit_event (
    id UUID PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""

_CREATE_RECOMMENDATION = """
CREATE TABLE IF NOT EXISTS recommendation (
    recommendation_id TEXT PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    asset_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    card JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""


class Store:
    """Audit + recommendation persistence with graceful in-memory fallback."""

    def __init__(self, database_url: str | None = None, *, connect: bool = True) -> None:
        self.database_url = database_url
        self.db_connected = False
        self._conn: Any = None
        self._lock = threading.RLock()

        # In-memory mirrors used whenever the database is unavailable.
        self._audit_mem: list[dict[str, Any]] = []
        self._rec_mem: dict[str, dict[str, Any]] = {}

        if connect and database_url:
            self._try_connect(database_url)

    # -- connection lifecycle -------------------------------------------------

    def _try_connect(self, database_url: str) -> None:
        try:
            import psycopg  # imported lazily so the package works without a driver
            from psycopg.types.json import Jsonb  # noqa: F401  (import-time capability check)

            self._conn = psycopg.connect(database_url, autocommit=True)
            self._ensure_tables()
            self.db_connected = True
            logger.info("store connected to database", extra={"db_connected": True})
        except Exception as exc:  # pragma: no cover - exercised only with a real DB
            self._conn = None
            self.db_connected = False
            logger.warning(
                "store falling back to in-memory mode",
                extra={"db_connected": False, "error": str(exc)},
            )

    def _ensure_tables(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_CREATE_AUDIT)
            cur.execute(_CREATE_RECOMMENDATION)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None
                    self.db_connected = False

    # -- audit ---------------------------------------------------------------

    def audit(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        """Record an audit event and return the stored record."""
        event = {
            "id": str(uuid.uuid4()),
            "ts": _utcnow(),
            "kind": kind,
            "actor": actor,
            "payload": payload or {},
        }
        with self._lock:
            if self.db_connected:
                try:
                    from psycopg.types.json import Jsonb

                    with self._conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO audit_event (id, ts, kind, actor, payload) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            (
                                event["id"],
                                event["ts"],
                                event["kind"],
                                event["actor"],
                                Jsonb(event["payload"]),
                            ),
                        )
                    return event
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning(
                        "audit write failed; mirroring to memory",
                        extra={"error": str(exc)},
                    )
            self._audit_mem.append(event)
        return event

    def recent_audit(self, n: int = 50) -> list[dict[str, Any]]:
        """Return up to ``n`` most-recent audit events, newest first."""
        with self._lock:
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute(
                            "SELECT id, ts, kind, actor, payload FROM audit_event "
                            "ORDER BY ts DESC LIMIT %s",
                            (n,),
                        )
                        rows = cur.fetchall()
                    return [
                        {
                            "id": str(r[0]),
                            "ts": r[1],
                            "kind": r[2],
                            "actor": r[3],
                            "payload": r[4],
                        }
                        for r in rows
                    ]
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("audit read failed; using memory", extra={"error": str(exc)})
            return list(reversed(self._audit_mem))[:n]

    # -- recommendations -----------------------------------------------------

    def save_recommendation(self, card: RecommendationCard) -> RecommendationCard:
        """Persist a recommendation card and return it."""
        card_json = card.as_card_payload()
        status = _status_value(card.approval_status)
        with self._lock:
            if self.db_connected:
                try:
                    from psycopg.types.json import Jsonb

                    with self._conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO recommendation "
                            "(recommendation_id, ts, asset_id, status, card) "
                            "VALUES (%s, %s, %s, %s, %s) "
                            "ON CONFLICT (recommendation_id) DO UPDATE SET "
                            "ts = EXCLUDED.ts, asset_id = EXCLUDED.asset_id, "
                            "status = EXCLUDED.status, card = EXCLUDED.card",
                            (
                                card.recommendation_id,
                                card.ts,
                                card.asset_id,
                                status,
                                Jsonb(card_json),
                            ),
                        )
                    return card
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning(
                        "recommendation write failed; mirroring to memory",
                        extra={"error": str(exc)},
                    )
            self._rec_mem[card.recommendation_id] = {
                "recommendation_id": card.recommendation_id,
                "ts": card.ts,
                "asset_id": card.asset_id,
                "status": status,
                "card": card_json,
            }
        return card

    def get_recommendation(self, recommendation_id: str) -> RecommendationCard | None:
        """Return a stored recommendation card, or ``None`` if unknown."""
        with self._lock:
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute(
                            "SELECT card FROM recommendation WHERE recommendation_id = %s",
                            (recommendation_id,),
                        )
                        row = cur.fetchone()
                    if row is None:
                        return None
                    return RecommendationCard.model_validate(row[0])
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("recommendation read failed; using memory",
                                   extra={"error": str(exc)})
            record = self._rec_mem.get(recommendation_id)
            if record is None:
                return None
            return RecommendationCard.model_validate(record["card"])

    def list_recommendations(self) -> list[RecommendationCard]:
        """Return all stored recommendation cards, newest first."""
        with self._lock:
            if self.db_connected:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute("SELECT card FROM recommendation ORDER BY ts DESC")
                        rows = cur.fetchall()
                    return [RecommendationCard.model_validate(r[0]) for r in rows]
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("recommendation list failed; using memory",
                                   extra={"error": str(exc)})
            records = sorted(
                self._rec_mem.values(),
                key=lambda rec: rec["ts"],
                reverse=True,
            )
            return [RecommendationCard.model_validate(rec["card"]) for rec in records]

    def set_approval(
        self,
        recommendation_id: str,
        status: str | ApprovalStatus,
        actor: str,
    ) -> RecommendationCard | None:
        """Update a recommendation's approval status and write an audit event.

        Returns the updated card, or ``None`` if the recommendation is unknown.
        This is an *operator approval* action only; it never writes to equipment.
        """
        status_value = _status_value(status)
        with self._lock:
            card = self.get_recommendation(recommendation_id)
            if card is None:
                return None

            card.approval_status = ApprovalStatus(status_value)
            self.save_recommendation(card)
            self.audit(
                "recommendation_approval",
                payload={
                    "recommendation_id": recommendation_id,
                    "status": status_value,
                    "asset_id": card.asset_id,
                },
                actor=actor,
            )
        return card
