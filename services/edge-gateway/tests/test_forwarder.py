"""Tests for the store-and-forward engine.

These prove the core resilience guarantee without any network or docker: a
gateway that is killed mid-stream (destination down and/or crash before ack)
recovers on restart with **no data loss and no duplication**, mirroring the
upstream API's idempotent ingest.
"""

from __future__ import annotations

from typing import Any

from app.forwarder import ForwardResult, Gateway
from app.spool import Spool


class FakeUpstream:
    """An in-process stand-in for the idempotent watertwin-api ingest path."""

    def __init__(self) -> None:
        self.available = True
        self.batches: dict[str, int] = {}  # batch_id -> reading count (dedup ledger)
        self.calls: list[str] = []

    def forward(self, payload: dict[str, Any]) -> ForwardResult:
        self.calls.append(payload["batch_id"])
        if not self.available:
            return ForwardResult(ok=False, error="api unreachable")
        batch_id = payload["batch_id"]
        duplicate = batch_id in self.batches
        if not duplicate:
            self.batches[batch_id] = len(payload["readings"])
        return ForwardResult(ok=True, duplicate=duplicate, status=200)


def _gateway(tmp_path, upstream: FakeUpstream) -> Gateway:
    return Gateway(spool=Spool(str(tmp_path)), forward_fn=upstream.forward, gateway_id="gw-test")


def test_happy_path_forwards_each_batch_once(tmp_path):
    upstream = FakeUpstream()
    gw = _gateway(tmp_path, upstream)

    for _ in range(5):
        gw.produce_once()
    forwarded = gw.drain()

    assert forwarded == 5
    assert gw.spool.depth() == 0
    assert len(upstream.batches) == 5
    snap = gw.stats.snapshot()
    assert snap["produced"] == 5
    assert snap["forwarded"] == 5
    assert snap["duplicates"] == 0


def test_batches_accumulate_while_api_is_down(tmp_path):
    upstream = FakeUpstream()
    upstream.available = False
    gw = _gateway(tmp_path, upstream)

    for _ in range(4):
        gw.produce_once()
    forwarded = gw.drain()  # nothing drains while upstream is down

    assert forwarded == 0
    assert gw.spool.depth() == 4
    assert gw.stats.snapshot()["api_reachable"] is False


def test_recovery_after_gateway_restart_is_lossless(tmp_path):
    upstream = FakeUpstream()

    # First lifetime: API is down, so 6 batches pile up on the durable spool.
    upstream.available = False
    gw1 = _gateway(tmp_path, upstream)
    for _ in range(6):
        gw1.produce_once()
    assert gw1.spool.depth() == 6

    # The gateway is killed (drop the object) with un-forwarded data on disk.
    del gw1

    # Second lifetime over the SAME spool dir; API is back. Also keep producing.
    upstream.available = True
    gw2 = _gateway(tmp_path, upstream)
    for _ in range(3):
        gw2.produce_once()
    forwarded = gw2.drain()

    assert gw2.spool.depth() == 0
    assert forwarded == 9  # 6 replayed + 3 new
    assert len(upstream.batches) == 9  # every distinct batch landed

    # batch ids are contiguous and unique across the restart (no reuse/gaps).
    ids = sorted(upstream.batches)
    assert ids == [f"gw-test-{seq:012d}" for seq in range(9)]


def test_crash_after_upstream_commit_before_ack_does_not_duplicate(tmp_path):
    upstream = FakeUpstream()
    gw1 = _gateway(tmp_path, upstream)
    for _ in range(3):
        gw1.produce_once()

    # Simulate a crash where the batch was durably accepted upstream but the
    # gateway died before it could ack/delete it from the spool: deliver the
    # oldest batch directly to upstream WITHOUT acking, then drop the gateway.
    stranded = gw1.spool.peek()
    assert stranded is not None
    result = upstream.forward(stranded.payload)
    assert result.ok and not result.duplicate
    del gw1

    # Restart over the same spool; the stranded batch is still on disk and gets
    # replayed. Upstream must de-duplicate it rather than double-count.
    gw2 = _gateway(tmp_path, upstream)
    forwarded = gw2.drain()

    assert forwarded == 3
    assert gw2.spool.depth() == 0
    assert len(upstream.batches) == 3  # no duplication despite the replay
    assert gw2.stats.snapshot()["duplicates"] == 1


def test_health_snapshot_shape(tmp_path):
    upstream = FakeUpstream()
    gw = _gateway(tmp_path, upstream)
    gw.produce_once()
    health = gw.health()
    assert health["service"] == "edge-gateway"
    assert health["control_write_enabled"] is False
    assert health["spool_depth"] == 1
    assert health["produced"] == 1
