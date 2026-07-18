"""Content-addressed, write-once storage: streaming sha256, key layout, dedup."""

from __future__ import annotations

import hashlib
import os
import re

import pytest

from app.storage import (
    LocalFilesystemBackend,
    OversizeError,
    S3CompatibleBackend,
    StorageError,
)


def _stage(backend, data: bytes, *, size_cap: int = 1 << 30):
    writer = backend.new_writer(size_cap)
    # Feed in two chunks to exercise incremental hashing.
    mid = len(data) // 2
    writer.write(data[:mid])
    writer.write(data[mid:])
    return writer.finish()


def test_streaming_sha256_matches_and_key_layout(tmp_path):
    backend = LocalFilesystemBackend(str(tmp_path))
    data = b"customer-lab-report-bytes" * 100
    staged = _stage(backend, data)
    assert staged.sha256 == hashlib.sha256(data).hexdigest()
    assert staged.size_bytes == len(data)

    stored = backend.commit(staged, "TEN-A")
    assert re.fullmatch(rf"TEN-A/\d{{4}}/\d{{2}}/{staged.sha256}", stored.key)
    assert backend.exists(stored.key)
    with backend.open(stored.key) as fh:
        assert fh.read() == data


def test_commit_is_write_once_and_dedups_identical_content(tmp_path):
    backend = LocalFilesystemBackend(str(tmp_path))
    data = b"identical-bytes"
    first = backend.commit(_stage(backend, data), "TEN-A")
    second = backend.commit(_stage(backend, data), "TEN-A")
    assert first.key == second.key
    assert first.deduplicated is False
    assert second.deduplicated is True
    # The committed object is read-only (no overwrite path exists).
    abs_path = os.path.join(str(tmp_path), first.key)
    mode = os.stat(abs_path).st_mode & 0o222
    assert mode == 0, "committed object must not be writable"


def test_oversize_raises_before_commit_and_leaves_nothing(tmp_path):
    backend = LocalFilesystemBackend(str(tmp_path))
    writer = backend.new_writer(size_cap=8)
    with pytest.raises(OversizeError):
        writer.write(b"way past the eight byte cap")
    # No object under the tenant root (staging file was removed on abort).
    staging = backend.staging_dir()
    leftover = [f for f in os.listdir(staging)] if os.path.isdir(staging) else []
    assert leftover == []


def test_s3_backend_is_stubbed_behind_same_interface(tmp_path):
    backend = S3CompatibleBackend(bucket="b", endpoint=None, prefix="")
    staged = _stage(LocalFilesystemBackend(str(tmp_path)), b"data")
    with pytest.raises(StorageError):
        backend.commit(staged, "TEN-A")
    with pytest.raises(StorageError):
        backend.exists("TEN-A/2026/01/abc")
