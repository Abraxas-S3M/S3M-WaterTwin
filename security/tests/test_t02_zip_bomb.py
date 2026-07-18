"""ADR-0014 T2 — Zip bomb (compression ratio / nesting depth / absolute size).

Control: archive inspection + extraction under hard caps on compression ratio,
nesting depth, cumulative uncompressed size, and member count.
"""

from __future__ import annotations

import io
import os
import zipfile

import pytest
from app.archives import (
    ArchiveLimits,
    ArchiveTooDeep,
    ArchiveTooLarge,
    CompressionBomb,
    inspect_zip,
    safe_extract,
)


def _make_zip(path: str, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def _nested_zip(path: str, depth: int) -> None:
    """Build an archive nested ``depth`` levels deep."""
    inner = b"payload"
    for _ in range(depth):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("inner.zip" if _ else "inner.bin", inner)
        inner = buf.getvalue()
    with open(path, "wb") as fh:
        fh.write(inner)


def test_compression_ratio_bomb_rejected(tmp_path):
    # Highly-compressible payload => huge uncompressed:compressed ratio.
    path = str(tmp_path / "ratio.zip")
    _make_zip(path, {"big.txt": b"\0" * (5 * 1024 * 1024)})
    limits = ArchiveLimits(max_compression_ratio=50.0)
    with pytest.raises(CompressionBomb):
        inspect_zip(path, limits)


def test_absolute_uncompressed_size_cap_rejected(tmp_path):
    path = str(tmp_path / "big.zip")
    _make_zip(path, {"a.bin": b"A" * (2 * 1024 * 1024)})
    limits = ArchiveLimits(
        max_total_uncompressed_bytes=1024 * 1024, max_compression_ratio=10_000.0
    )
    with pytest.raises(ArchiveTooLarge):
        inspect_zip(path, limits)


def test_member_count_cap_rejected(tmp_path):
    path = str(tmp_path / "many.zip")
    _make_zip(path, {f"f{i}.txt": b"x" for i in range(50)})
    limits = ArchiveLimits(max_members=10)
    with pytest.raises(ArchiveTooLarge):
        inspect_zip(path, limits)


def test_nesting_depth_cap_rejected(tmp_path):
    path = str(tmp_path / "nested.zip")
    _nested_zip(path, depth=5)
    limits = ArchiveLimits(max_depth=2, max_compression_ratio=10_000.0)
    dest = str(tmp_path / "out")
    with pytest.raises(ArchiveTooDeep):
        safe_extract(path, dest, limits)


def test_benign_archive_extracts_within_limits(tmp_path):
    path = str(tmp_path / "ok.zip")
    _make_zip(path, {"lab.csv": b"analyte,value\nturbidity,0.3\n"})
    dest = str(tmp_path / "out")
    extracted = safe_extract(path, dest, ArchiveLimits(max_compression_ratio=10_000.0))
    assert len(extracted) == 1
    assert os.path.isfile(extracted[0])
