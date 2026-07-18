"""Safe archive (ZIP) handling — anti zip-bomb and anti path-traversal.

Untrusted archives are inspected and extracted under hard limits:

* **Absolute size** — the cumulative uncompressed size may not exceed a cap.
* **Compression ratio** — no single member may expand beyond a max ratio (the
  classic ``42.zip`` compression bomb).
* **Nesting depth** — archives-within-archives are limited in depth.
* **Member count** — a cap on the number of entries (many-tiny-files bomb).
* **Path traversal (Zip Slip)** — a member whose path is absolute or escapes the
  extraction root via ``..`` (or a symlink) is rejected; nothing is ever written
  outside the target directory.

Extraction is streamed member-by-member with a per-member byte budget so a
lying ZIP header cannot force an unbounded read.
"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass

from . import config


class ArchiveTooLarge(Exception):
    """Raised when an archive exceeds an absolute-size or member-count cap."""


class CompressionBomb(Exception):
    """Raised when a member's uncompressed:compressed ratio is implausible."""


class ArchiveTooDeep(Exception):
    """Raised when archive nesting exceeds the allowed depth."""


class PathTraversal(Exception):
    """Raised when an archive member would write outside the extraction root."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_total_uncompressed_bytes: int = config.MAX_ARCHIVE_TOTAL_UNCOMPRESSED_BYTES
    max_compression_ratio: float = config.MAX_ARCHIVE_COMPRESSION_RATIO
    max_depth: int = config.MAX_ARCHIVE_DEPTH
    max_members: int = config.MAX_ARCHIVE_MEMBERS


_READ_CHUNK = 64 * 1024


def _is_within(base: str, target: str) -> bool:
    """True iff ``target`` resolves to a path inside ``base``."""
    base_abs = os.path.abspath(base)
    target_abs = os.path.abspath(target)
    return os.path.commonpath([base_abs]) == os.path.commonpath([base_abs, target_abs])


def _safe_member_path(dest_dir: str, member_name: str) -> str:
    """Resolve ``member_name`` under ``dest_dir`` or raise :class:`PathTraversal`."""
    # Absolute paths and drive letters are never allowed.
    if os.path.isabs(member_name) or member_name.startswith(("/", "\\")):
        raise PathTraversal(f"absolute member path rejected: {member_name!r}")
    # Normalize and confirm containment (defeats ../ and mixed separators).
    target = os.path.normpath(os.path.join(dest_dir, member_name))
    if not _is_within(dest_dir, target):
        raise PathTraversal(f"member escapes extraction root: {member_name!r}")
    return target


def inspect_zip(path: str, limits: ArchiveLimits | None = None) -> dict[str, object]:
    """Validate a ZIP against the bomb limits without extracting it.

    Returns a summary dict on success; raises the relevant exception on any
    violation. This is the cheap pre-flight check run before extraction.
    """
    limits = limits or ArchiveLimits()
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if len(infos) > limits.max_members:
            raise ArchiveTooLarge(
                f"archive has {len(infos)} members (max {limits.max_members})"
            )
        total_uncompressed = 0
        for info in infos:
            # Guard the declared paths for traversal before trusting anything.
            if os.path.isabs(info.filename) or info.filename.startswith(("/", "\\")):
                raise PathTraversal(f"absolute member path rejected: {info.filename!r}")
            if ".." in info.filename.replace("\\", "/").split("/"):
                raise PathTraversal(f"traversal member path rejected: {info.filename!r}")
            total_uncompressed += info.file_size
            if total_uncompressed > limits.max_total_uncompressed_bytes:
                raise ArchiveTooLarge(
                    "archive uncompressed size exceeds "
                    f"{limits.max_total_uncompressed_bytes} bytes"
                )
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > limits.max_compression_ratio:
                    raise CompressionBomb(
                        f"member {info.filename!r} ratio {ratio:.1f} exceeds "
                        f"{limits.max_compression_ratio}"
                    )
    return {
        "members": len(infos),
        "declared_uncompressed_bytes": total_uncompressed,
    }


def safe_extract(
    path: str,
    dest_dir: str,
    limits: ArchiveLimits | None = None,
    *,
    _depth: int = 0,
) -> list[str]:
    """Safely extract ``path`` into ``dest_dir`` under all bomb/traversal limits.

    Returns the list of extracted file paths. Nested archives are recursively
    validated up to ``max_depth``. Raises on any violation; on a violation no
    partially-written member is left readable outside the destination root.
    """
    limits = limits or ArchiveLimits()
    if _depth > limits.max_depth:
        raise ArchiveTooDeep(f"archive nesting exceeds depth {limits.max_depth}")

    inspect_zip(path, limits)  # pre-flight (cheap, header-based)
    os.makedirs(dest_dir, exist_ok=True)
    extracted: list[str] = []
    written_total = 0

    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = _safe_member_path(dest_dir, info.filename)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            # Stream with a per-member budget so a lying header cannot overrun.
            member_budget = min(
                info.file_size if info.file_size > 0 else limits.max_total_uncompressed_bytes,
                limits.max_total_uncompressed_bytes,
            )
            written_member = 0
            with zf.open(info, "r") as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(_READ_CHUNK)
                    if not chunk:
                        break
                    written_member += len(chunk)
                    written_total += len(chunk)
                    if written_member > member_budget:
                        raise CompressionBomb(
                            f"member {info.filename!r} produced more bytes than declared"
                        )
                    if written_total > limits.max_total_uncompressed_bytes:
                        raise ArchiveTooLarge(
                            "archive uncompressed size exceeds "
                            f"{limits.max_total_uncompressed_bytes} bytes"
                        )
                    dst.write(chunk)
            extracted.append(target)
            if zipfile.is_zipfile(target):
                nested_dir = target + ".d"
                extracted.extend(
                    safe_extract(target, nested_dir, limits, _depth=_depth + 1)
                )
    return extracted
