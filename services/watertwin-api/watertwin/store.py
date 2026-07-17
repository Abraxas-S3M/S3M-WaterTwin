"""In-memory store for telemetry, recommendations and audit events.

Phase 6 uses a thread-safe in-memory store. Phase 10 replaces the persistence
layer with TimescaleDB; ``db_connected`` reports ``False`` here to reflect that
no external database is wired up yet.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .models import AuditEvent, RecommendationCard, TelemetryReading

HISTORY_LIMIT = 500
AUDIT_LIMIT = 1000


class Store:
    def __init__(self, history_limit: int = HISTORY_LIMIT) -> None:
        self._lock = threading.RLock()
        self._history_limit = history_limit
        self._latest: dict[str, TelemetryReading] = {}
        self._history: dict[str, deque[TelemetryReading]] = defaultdict(
            lambda: deque(maxlen=history_limit)
        )
        self._recommendations: dict[str, RecommendationCard] = {}
        self._audit: deque[AuditEvent] = deque(maxlen=AUDIT_LIMIT)

    @property
    def db_connected(self) -> bool:
        # No external database in Phase 6 (in-memory only).
        return False

    def ingest(self, readings: list[TelemetryReading]) -> None:
        with self._lock:
            for reading in readings:
                self._latest[reading.asset_id] = reading
                self._history[reading.asset_id].append(reading)

    def latest_all(self) -> list[TelemetryReading]:
        with self._lock:
            return list(self._latest.values())

    def latest_for(self, asset_id: str) -> TelemetryReading | None:
        with self._lock:
            return self._latest.get(asset_id)

    def history_for(self, asset_id: str, limit: int | None = None) -> list[TelemetryReading]:
        with self._lock:
            items = list(self._history.get(asset_id, ()))
        if limit is not None:
            return items[-limit:]
        return items

    def save_recommendation(self, card: RecommendationCard) -> None:
        with self._lock:
            self._recommendations[card.id] = card

    def get_recommendation(self, rec_id: str) -> RecommendationCard | None:
        with self._lock:
            return self._recommendations.get(rec_id)

    def recommendations(self) -> list[RecommendationCard]:
        with self._lock:
            return sorted(
                self._recommendations.values(),
                key=lambda c: c.created_at,
                reverse=True,
            )

    def set_approval(
        self, rec_id: str, status: str, actor: str
    ) -> RecommendationCard | None:
        with self._lock:
            card = self._recommendations.get(rec_id)
            if card is None:
                return None
            updated = card.model_copy(
                update={
                    "approval_status": status,
                    "decided_at": datetime.now(UTC),
                    "decided_by": actor,
                }
            )
            self._recommendations[rec_id] = updated
            return updated

    def add_audit(
        self, event_type: str, actor: str, subject: str, details: dict[str, Any] | None = None
    ) -> AuditEvent:
        event = AuditEvent(
            id=str(uuid4()),
            timestamp=datetime.now(UTC),
            event_type=event_type,
            actor=actor,
            subject=subject,
            details=details or {},
        )
        with self._lock:
            self._audit.append(event)
        return event

    def audit_events(self, limit: int = 100) -> list[AuditEvent]:
        with self._lock:
            items = list(self._audit)
        return list(reversed(items))[:limit]

    def reset(self) -> None:
        with self._lock:
            self._latest.clear()
            self._history.clear()
            self._recommendations.clear()
            self._audit.clear()
