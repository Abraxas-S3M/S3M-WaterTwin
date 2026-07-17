"""Buffer tests: persistence across restart + encryption at rest."""

from __future__ import annotations

import sqlite3


from app.buffer import EncryptedBuffer, derive_fernet_key


def _reading(asset="AST-HPP-01", metric="winding_temp_c", value=150.0):
    return {
        "asset_id": asset,
        "metric": metric,
        "value": value,
        "unit": "degC",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "provenance": "measured",
        "quality": "good",
    }


def test_buffer_persists_across_restart(tmp_path):
    path = str(tmp_path / "buffer.db")

    # First "process": append three readings, then shut down.
    buf = EncryptedBuffer(path, key="stable-key")
    buf.append_many([_reading(value=150.0), _reading(value=151.0), _reading(value=152.0)])
    assert buf.count() == 3
    buf.close()

    # Second "process": the same buffer file reopens with the same key and still
    # holds every unacknowledged reading (FIFO order preserved).
    reopened = EncryptedBuffer(path, key="stable-key")
    assert reopened.count() == 3
    pending = reopened.pending()
    assert [rec["value"] for _, rec in pending] == [150.0, 151.0, 152.0]
    assert pending[0][1]["asset_id"] == "AST-HPP-01"
    reopened.close()


def test_buffer_survives_partial_ack_across_restart(tmp_path):
    path = str(tmp_path / "buffer.db")
    buf = EncryptedBuffer(path, key="stable-key")
    ids = buf.append_many([_reading(value=1.0), _reading(value=2.0), _reading(value=3.0)])
    # Acknowledge only the first row (as a successful partial forward would).
    buf.ack(ids[:1])
    buf.close()

    reopened = EncryptedBuffer(path, key="stable-key")
    assert reopened.count() == 2
    assert [rec["value"] for _, rec in reopened.pending()] == [2.0, 3.0]
    reopened.close()


def test_buffer_is_encrypted_at_rest(tmp_path):
    path = str(tmp_path / "buffer.db")
    buf = EncryptedBuffer(path, key="stable-key")
    buf.append(_reading(asset="SECRET-ASSET-XYZ", metric="secret_metric", value=42.0))
    buf.close()

    # The stored payload column must be ciphertext -- no plaintext markers.
    con = sqlite3.connect(path)
    try:
        payloads = [bytes(row[0]) for row in con.execute("SELECT payload FROM outbox")]
    finally:
        con.close()
    assert payloads, "expected a buffered row"
    blob = payloads[0]
    # Distinctive plaintext markers must not appear in the at-rest ciphertext.
    assert b"SECRET-ASSET-XYZ" not in blob
    assert b"secret_metric" not in blob


def test_buffer_with_wrong_key_cannot_read(tmp_path):
    path = str(tmp_path / "buffer.db")
    buf = EncryptedBuffer(path, key="right-key")
    buf.append(_reading())
    buf.close()

    # Opening with the wrong key cannot decrypt: undecryptable rows are dropped
    # rather than surfaced as garbage.
    wrong = EncryptedBuffer(path, key="wrong-key")
    assert wrong.pending() == []
    wrong.close()


def test_derive_fernet_key_is_stable_and_valid():
    from cryptography.fernet import Fernet

    k1 = derive_fernet_key("passphrase")
    k2 = derive_fernet_key("passphrase")
    assert k1 == k2
    # A derived key is a usable Fernet key.
    token = Fernet(k1).encrypt(b"hello")
    assert Fernet(k2).decrypt(token) == b"hello"
    assert derive_fernet_key("other") != k1
