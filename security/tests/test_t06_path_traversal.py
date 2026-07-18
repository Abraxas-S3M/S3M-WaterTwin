"""ADR-0014 T6 — Archive path traversal (Zip Slip).

Control: safe extraction rejects any member whose path is absolute or escapes
the extraction root via ``..``; nothing is ever written outside the target dir.
"""

from __future__ import annotations

import os
import zipfile

import pytest
from app.archives import ArchiveLimits, PathTraversal, inspect_zip, safe_extract

_LIMITS = ArchiveLimits(max_compression_ratio=10_000.0)


def _write_zip_with_raw_name(path: str, arcname: str, data: bytes) -> None:
    """Write a zip whose member name is set verbatim (allows crafting ../)."""
    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo(filename=arcname)
        zf.writestr(info, data)


def test_relative_traversal_member_rejected_on_inspect(tmp_path):
    path = str(tmp_path / "evil.zip")
    _write_zip_with_raw_name(path, "../../etc/evil.conf", b"pwned")
    with pytest.raises(PathTraversal):
        inspect_zip(path, _LIMITS)


def test_relative_traversal_member_rejected_on_extract(tmp_path):
    path = str(tmp_path / "evil.zip")
    _write_zip_with_raw_name(path, "../escape.txt", b"pwned")
    dest = str(tmp_path / "out")
    with pytest.raises(PathTraversal):
        safe_extract(path, dest, _LIMITS)
    # Nothing escaped the destination root.
    assert not os.path.exists(str(tmp_path / "escape.txt"))


def test_absolute_member_path_rejected(tmp_path):
    path = str(tmp_path / "abs.zip")
    _write_zip_with_raw_name(path, "/etc/evil.conf", b"pwned")
    with pytest.raises(PathTraversal):
        inspect_zip(path, _LIMITS)


def test_safe_members_extract_inside_root(tmp_path):
    path = str(tmp_path / "ok.zip")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("sub/dir/lab.csv", b"analyte,value\n")
    dest = str(tmp_path / "out")
    extracted = safe_extract(path, dest, _LIMITS)
    assert len(extracted) == 1
    real = os.path.realpath(extracted[0])
    assert real.startswith(os.path.realpath(dest) + os.sep)
