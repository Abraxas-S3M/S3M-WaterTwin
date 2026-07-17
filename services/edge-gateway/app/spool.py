"""Durable, ordered store-and-forward spool.

Each telemetry batch produced by the gateway is written to its own JSON file in
:attr:`Spool.dir`, named by a zero-padded, monotonically increasing sequence so
files replay in production order. A batch is only removed once the central API
has acknowledged it (``ack``). Because the spool lives on a mounted volume, an
un-forwarded batch survives a gateway crash/restart and is replayed on recovery,
giving lossless store-and-forward. The upstream ingest path is idempotent on the
batch id, so a batch that was delivered but crashed before ``ack`` is de-duped
rather than double-counted.

Writes are atomic (write to a ``*.tmp`` sibling then ``os.replace``) so a crash
mid-write never leaves a partially-written batch to be forwarded.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from typing import Any, Optional

_SEQ_WIDTH = 12
_BATCH_SUFFIX = ".batch.json"
_SEQ_FILE = ".next_seq"


@dataclass(frozen=True)
class SpooledBatch:
    """A batch read back from the spool, with the file backing it."""

    seq: int
    path: str
    payload: dict[str, Any]


class Spool:
    """A durable, ordered on-disk queue of telemetry batches."""

    def __init__(self, directory: str) -> None:
        self.dir = directory
        self._lock = threading.RLock()
        os.makedirs(self.dir, exist_ok=True)
        self._next_seq = self._recover_next_seq()

    # -- sequence numbering ---------------------------------------------------

    def _seq_path(self) -> str:
        return os.path.join(self.dir, _SEQ_FILE)

    def _recover_next_seq(self) -> int:
        """Resume numbering above any batch ever produced.

        The persisted counter guarantees ids are never reused (reusing an id for
        different content would silently drop data under idempotent ingest). We
        also take the max of any still-spooled file so a lost counter cannot
        collide with pending work.
        """
        persisted = 0
        try:
            with open(self._seq_path(), encoding="utf-8") as handle:
                persisted = int(handle.read().strip() or "0")
        except (FileNotFoundError, ValueError):
            persisted = 0

        highest_pending = 0
        for entry in os.listdir(self.dir):
            if entry.endswith(_BATCH_SUFFIX):
                try:
                    highest_pending = max(highest_pending, int(entry[:_SEQ_WIDTH]) + 1)
                except ValueError:
                    continue
        return max(persisted, highest_pending)

    def _persist_next_seq(self, value: int) -> None:
        tmp = self._seq_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(str(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self._seq_path())

    # -- queue operations -----------------------------------------------------

    def next_seq(self) -> int:
        """Reserve and return the next monotonic batch sequence number."""
        with self._lock:
            seq = self._next_seq
            self._next_seq = seq + 1
            self._persist_next_seq(self._next_seq)
            return seq

    def _batch_path(self, seq: int) -> str:
        return os.path.join(self.dir, f"{seq:0{_SEQ_WIDTH}d}{_BATCH_SUFFIX}")

    def append(self, seq: int, payload: dict[str, Any]) -> str:
        """Atomically write ``payload`` for ``seq`` and return its file path."""
        path = self._batch_path(seq)
        tmp = path + ".tmp"
        with self._lock:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        return path

    def pending(self) -> list[SpooledBatch]:
        """Return all un-acked batches, oldest (lowest seq) first."""
        with self._lock:
            items: list[SpooledBatch] = []
            for entry in sorted(os.listdir(self.dir)):
                if not entry.endswith(_BATCH_SUFFIX):
                    continue
                try:
                    seq = int(entry[:_SEQ_WIDTH])
                except ValueError:
                    continue
                path = os.path.join(self.dir, entry)
                try:
                    with open(path, encoding="utf-8") as handle:
                        payload = json.load(handle)
                except (json.JSONDecodeError, FileNotFoundError):
                    # A partially-written or vanished file: skip it (a *.tmp is
                    # never picked up because it lacks the batch suffix).
                    continue
                items.append(SpooledBatch(seq=seq, path=path, payload=payload))
            return items

    def peek(self) -> Optional[SpooledBatch]:
        """Return the oldest un-acked batch, or ``None`` when the spool is empty."""
        batches = self.pending()
        return batches[0] if batches else None

    def ack(self, batch: SpooledBatch) -> None:
        """Remove ``batch`` from the spool (it was durably accepted upstream)."""
        with self._lock:
            try:
                os.remove(batch.path)
            except FileNotFoundError:
                pass

    def depth(self) -> int:
        """Number of un-acked batches currently spooled."""
        with self._lock:
            return sum(1 for e in os.listdir(self.dir) if e.endswith(_BATCH_SUFFIX))
