"""Store-and-forward: readings survive an outage and replay when it clears."""

from __future__ import annotations

import types

import pytest

from app.buffer import EncryptedBuffer
from app.collector import Collector
from app.forwarder import ForwardResult


class FakeForwarder:
    """A controllable outbound forwarder (no real network)."""

    def __init__(self) -> None:
        self.online = True
        self.received: list[dict] = []
        self.calls = 0
        self.last_health: dict | None = None

    def send(self, records, *, source=None, fallback=False, source_health=None):
        self.calls += 1
        self.last_health = source_health
        if not self.online:
            return ForwardResult(ok=False, error="simulated outage")
        self.received.extend(records)
        return ForwardResult(ok=True, accepted=len(records))


def _config(tmp_path):
    return types.SimpleNamespace(
        OT_SOURCE="synthetic",
        GATEWAY_ID="edge-gw-test",
        FORWARD_BATCH_SIZE=1000,
        POLL_INTERVAL_S=0.0,
        STALENESS_LIMIT_S=1e9,  # never stale in tests
        FROZEN_LIMIT=10_000,    # never frozen in tests
        DEADBAND=0.0,
    )


@pytest.fixture()
def collector(tmp_path):
    buffer = EncryptedBuffer(str(tmp_path / "buffer.db"), key="k")
    forwarder = FakeForwarder()
    coll = Collector(_config(tmp_path), buffer, forwarder)
    yield coll, buffer, forwarder
    buffer.close()


def test_readings_buffer_during_outage_and_replay_after(collector):
    coll, buffer, forwarder = collector

    # --- outage: pushes fail, everything collected stays buffered ---
    forwarder.online = False
    coll.collect_once()
    n_first = buffer.count()
    assert n_first > 0, "synthetic collection should buffer readings"
    result = coll.flush_once()
    assert result.ok is False
    assert buffer.count() == n_first  # nothing acked during the outage
    assert forwarder.received == []

    # A second cycle during the outage keeps accumulating (no data loss).
    coll.collect_once()
    assert buffer.count() > n_first
    coll.flush_once()
    buffered_during_outage = buffer.count()
    assert forwarder.received == []

    # --- recovery: the backlog replays and the buffer drains ---
    forwarder.online = True
    result = coll.flush_once()
    assert result.ok is True
    assert buffer.count() == 0
    assert len(forwarder.received) == buffered_during_outage
    # The replayed batch carried the gateway source-health snapshot.
    assert forwarder.last_health is not None
    assert forwarder.last_health["gateway_id"] == "edge-gw-test"


def test_buffered_backlog_replays_across_restart(collector, tmp_path):
    coll, buffer, forwarder = collector

    # Accumulate a backlog during an outage, then "restart" the buffer.
    forwarder.online = False
    coll.run_once()
    coll.run_once()
    backlog = buffer.count()
    assert backlog > 0
    buffer.close()

    # New process: same buffer file, backlog intact, forwarder healthy again.
    reopened = EncryptedBuffer(str(tmp_path / "buffer.db"), key="k")
    forwarder.online = True
    coll2 = Collector(_config(tmp_path), reopened, forwarder)
    result = coll2.flush_once()
    assert result.ok is True
    assert reopened.count() == 0
    assert len(forwarder.received) == backlog
    reopened.close()
