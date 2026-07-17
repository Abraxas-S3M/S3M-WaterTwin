"""Local encrypted store-and-forward buffer (SQLite, encrypted at rest).

Every reading the gateway collects is appended to a durable local queue before
any push is attempted, so nothing is lost across process restarts or network
outages. Rows are **encrypted at rest**: each payload is stored as a Fernet
token (AES-128-CBC + HMAC-SHA256 authenticated encryption); the SQLite file
never contains plaintext telemetry. The Fernet key is derived from a configured
passphrase and is held only in memory / env -- never written to the buffer.

The queue is strictly FIFO: :meth:`pending` returns the oldest rows, the
forwarder pushes them, and :meth:`ack` deletes exactly those rows once the push
is acknowledged. Unacknowledged rows remain buffered and are retried.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sqlite3
import threading
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken

from canonical_water_model import now_iso

logger = logging.getLogger("edge_gateway.buffer")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enqueued_at TEXT NOT NULL,
    payload BLOB NOT NULL
);
"""


def derive_fernet_key(passphrase: str) -> bytes:
    """Derive a valid Fernet key (urlsafe base64 of 32 bytes) from a passphrase.

    Lets operators configure any human-friendly ``EDGE_GATEWAY_BUFFER_KEY`` while
    still producing a well-formed Fernet key. The same passphrase always yields
    the same key, so a restart can decrypt previously-buffered rows.
    """
    digest = hashlib.sha256(passphrase.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class EncryptedBuffer:
    """A durable, encrypted-at-rest FIFO store-and-forward queue."""

    def __init__(
        self,
        path: str,
        *,
        key: Optional[str] = None,
        max_rows: int = 500_000,
    ) -> None:
        self.path = path
        self.max_rows = max_rows
        self._lock = threading.RLock()

        if key:
            self._fernet = Fernet(derive_fernet_key(key))
            self._ephemeral = False
        else:
            # No configured key: encrypt with an ephemeral key so at-rest data is
            # still ciphertext, but warn -- rows cannot be recovered after a
            # restart (a new key is generated each boot).
            self._fernet = Fernet(Fernet.generate_key())
            self._ephemeral = True
            logger.warning(
                "EDGE_GATEWAY_BUFFER_KEY is not set: using an EPHEMERAL encryption "
                "key. Buffered rows will be unreadable after a restart. Set a "
                "stable key to persist the store-and-forward buffer encrypted."
            )

        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)

        # check_same_thread=False + our own lock: the collector loop and any
        # flush share one connection safely.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # pragma: no cover - defensive
                pass

    # -- encryption -----------------------------------------------------------

    def _encrypt(self, record: dict[str, Any]) -> bytes:
        return self._fernet.encrypt(json.dumps(record, separators=(",", ":")).encode("utf-8"))

    def _decrypt(self, token: bytes) -> Optional[dict[str, Any]]:
        try:
            return json.loads(self._fernet.decrypt(bytes(token)).decode("utf-8"))
        except (InvalidToken, ValueError) as exc:
            logger.warning("dropping undecryptable buffered row: %s", exc)
            return None

    # -- queue operations -----------------------------------------------------

    def append(self, record: dict[str, Any]) -> int:
        """Append a single record; returns its row id."""
        return self.append_many([record])[0]

    def append_many(self, records: list[dict[str, Any]]) -> list[int]:
        """Append a batch of records (encrypted); returns their row ids in order."""
        if not records:
            return []
        ts = now_iso()
        ids: list[int] = []
        with self._lock:
            cur = self._conn.cursor()
            for record in records:
                cur.execute(
                    "INSERT INTO outbox (enqueued_at, payload) VALUES (?, ?)",
                    (ts, self._encrypt(record)),
                )
                ids.append(int(cur.lastrowid))
            self._conn.commit()
            self._trim_locked()
        return ids

    def pending(self, limit: int = 500) -> list[tuple[int, dict[str, Any]]]:
        """Return up to ``limit`` oldest ``(id, record)`` rows (FIFO)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, payload FROM outbox ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        out: list[tuple[int, dict[str, Any]]] = []
        undecryptable: list[int] = []
        for row_id, payload in rows:
            record = self._decrypt(payload)
            if record is None:
                undecryptable.append(int(row_id))
            else:
                out.append((int(row_id), record))
        if undecryptable:
            self.ack(undecryptable)
        return out

    def ack(self, ids: list[int]) -> int:
        """Delete acknowledged rows by id; returns the number removed."""
        if not ids:
            return 0
        with self._lock:
            placeholders = ",".join("?" for _ in ids)
            cur = self._conn.execute(
                f"DELETE FROM outbox WHERE id IN ({placeholders})", tuple(ids)
            )
            self._conn.commit()
            return int(cur.rowcount)

    def count(self) -> int:
        """Number of rows currently buffered (unacknowledged)."""
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])

    # -- backpressure ---------------------------------------------------------

    def _trim_locked(self) -> None:
        """Drop the oldest rows past ``max_rows`` (bounded backpressure)."""
        if self.max_rows <= 0:
            return
        count = int(self._conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])
        if count <= self.max_rows:
            return
        overflow = count - self.max_rows
        self._conn.execute(
            "DELETE FROM outbox WHERE id IN "
            "(SELECT id FROM outbox ORDER BY id ASC LIMIT ?)",
            (overflow,),
        )
        self._conn.commit()
        logger.warning("buffer over capacity: dropped %d oldest row(s)", overflow)
