"""Archive-bomb defences: ratio, nesting depth, absolute uncompressed size, and
unsafe (``..`` / absolute) member paths -- one test each."""

from __future__ import annotations

from helpers import make_zip, make_zip_with_unsafe_member, upload


def _engineer(client):
    return client.token("erin-engineer", ["engineer"], "TEN-A")


def _upload_zip(client, content):
    return upload(
        client,
        filename="bundle.zip",
        content=content,
        content_type="application/zip",
        declared_class="archive",
        headers=_engineer(client),
    )


def test_zip_bomb_compression_ratio_is_rejected(client):
    # Highly compressible payload: tiny compressed, huge uncompressed => ratio cap.
    content = make_zip({"big.txt": b"0" * (5 * 1024 * 1024)})
    resp = _upload_zip(client, content)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "archive_ratio"


def test_zip_bomb_absolute_uncompressed_size_is_rejected(client, monkeypatch):
    from app import config

    # Poorly-compressible payload so the ratio cap does not fire first; lower the
    # absolute uncompressed cap so the size cap is what rejects it.
    import os

    monkeypatch.setattr(config, "ARCHIVE_MAX_TOTAL_UNCOMPRESSED_BYTES", 1000, raising=False)
    content = make_zip({"blob.bin": os.urandom(5000)})
    resp = _upload_zip(client, content)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "archive_size"


def test_zip_bomb_nesting_depth_is_rejected(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "ARCHIVE_MAX_NESTING_DEPTH", 0, raising=False)
    inner = make_zip({"inner.txt": b"hello"})
    content = make_zip({"inner.zip": inner})
    resp = _upload_zip(client, content)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "archive_depth"


def test_archive_member_with_traversal_is_rejected(client):
    content = make_zip_with_unsafe_member("../../etc/evil.txt")
    resp = _upload_zip(client, content)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "archive_unsafe_path"


def test_archive_member_with_absolute_path_is_rejected(client):
    content = make_zip_with_unsafe_member("/etc/evil.txt")
    resp = _upload_zip(client, content)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "archive_unsafe_path"
