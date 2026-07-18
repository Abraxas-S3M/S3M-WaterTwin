"""Unit tests for the operator-feedback store methods (in-memory path).

These lock the durable-store contract that the condition-intelligence
back-test / calibration harnesses depend on: a confirm/dismiss decision is
persisted, retrievable per alert (oldest first), and ordered newest-first when
listed recently — all without any control-write side effect. They run purely
on the in-memory mirror (``connect=False``) so no database is required.
"""

from __future__ import annotations

import pytest

from app.store import Store


@pytest.fixture()
def store() -> Store:
    return Store(database_url=None, connect=False)


def test_record_feedback_then_feedback_for_round_trip(store: Store) -> None:
    first = store.record_feedback(
        "alert-dp-01",
        "confirm",
        model_id="normalized-dp-fouling",
        asset_id="AST-MEMB-01",
        note="confirmed on inspection",
    )
    second = store.record_feedback("alert-dp-01", "dismiss", actor="op-2")
    # A decision on a different alert must not leak into the first alert's view.
    store.record_feedback("alert-other", "confirm")

    assert first["feedback_id"] != second["feedback_id"]
    assert first["decision"] == "confirm"

    for_alert = store.feedback_for("alert-dp-01")
    assert [f["feedback_id"] for f in for_alert] == [
        first["feedback_id"],
        second["feedback_id"],
    ]
    # feedback_for is oldest-first.
    assert [f["decision"] for f in for_alert] == ["confirm", "dismiss"]


def test_recent_feedback_orders_newest_first_and_honours_limit(store: Store) -> None:
    for i in range(5):
        store.record_feedback(f"alert-{i}", "confirm")

    recent = store.recent_feedback()
    # Newest first: the last-recorded alert leads.
    assert [f["alert_id"] for f in recent] == [
        "alert-4",
        "alert-3",
        "alert-2",
        "alert-1",
        "alert-0",
    ]

    # The ``n`` limit returns only the most-recent decisions, still newest-first.
    limited = store.recent_feedback(2)
    assert [f["alert_id"] for f in limited] == ["alert-4", "alert-3"]


def test_record_feedback_rejects_unknown_decision(store: Store) -> None:
    with pytest.raises(ValueError):
        store.record_feedback("alert-x", "maybe")
