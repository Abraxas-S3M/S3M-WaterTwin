"""Tests for the durable, ordered store-and-forward spool."""

from __future__ import annotations

from app.spool import Spool


def test_append_and_pending_are_ordered(tmp_path):
    spool = Spool(str(tmp_path))
    for _ in range(5):
        seq = spool.next_seq()
        spool.append(seq, {"batch_id": f"gw-{seq:012d}", "readings": []})

    pending = spool.pending()
    assert [b.seq for b in pending] == [0, 1, 2, 3, 4]
    assert spool.depth() == 5


def test_ack_removes_batch(tmp_path):
    spool = Spool(str(tmp_path))
    seq = spool.next_seq()
    spool.append(seq, {"batch_id": "gw-x", "readings": []})
    batch = spool.peek()
    assert batch is not None
    spool.ack(batch)
    assert spool.depth() == 0
    assert spool.peek() is None


def test_next_seq_persists_and_resumes_across_restart(tmp_path):
    spool = Spool(str(tmp_path))
    seqs = [spool.next_seq() for _ in range(3)]
    assert seqs == [0, 1, 2]

    # A fresh Spool over the same dir (simulating a restart) must never reuse an
    # already-issued sequence number.
    restarted = Spool(str(tmp_path))
    assert restarted.next_seq() == 3


def test_restart_resumes_above_pending_even_without_counter(tmp_path):
    spool = Spool(str(tmp_path))
    for _ in range(4):
        seq = spool.next_seq()
        spool.append(seq, {"batch_id": f"gw-{seq:012d}", "readings": []})

    # Lose the persisted counter (e.g. it never flushed) but keep spooled files.
    (tmp_path / ".next_seq").unlink()
    restarted = Spool(str(tmp_path))
    # Must resume above the highest still-pending batch (3), so no id collision.
    assert restarted.next_seq() == 4


def test_partial_tmp_file_is_ignored(tmp_path):
    spool = Spool(str(tmp_path))
    seq = spool.next_seq()
    spool.append(seq, {"batch_id": "gw-ok", "readings": []})
    # A leftover atomic-write temp file must never be treated as a batch.
    (tmp_path / "000000000009.batch.json.tmp").write_text("{partial", encoding="utf-8")
    assert spool.depth() == 1
    assert [b.seq for b in spool.pending()] == [seq]
