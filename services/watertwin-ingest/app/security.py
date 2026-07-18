"""Security helpers shared by the bulk-import parsers.

Two concerns live here:

1. **Archive member path sanitization** (reused from the Phase B archive checks):
   a zip / archive member must never escape the extraction root via an absolute
   path, a ``..`` traversal, or a drive/UNC prefix. Any such member causes the
   whole archive to be rejected -- we do not silently skip it.
2. **Safe XML parsing**: any XML we touch is parsed with :mod:`defusedxml` with
   DTD processing and entity expansion disabled, so an external-entity (XXE)
   attack surface does not exist.
"""

from __future__ import annotations

import posixpath
from pathlib import PurePosixPath
from typing import Any

from defusedxml.ElementTree import fromstring as _defused_fromstring
from defusedxml.ElementTree import parse as _defused_parse


class UnsafeArchiveMemberError(ValueError):
    """Raised when an archive member path would escape the extraction root."""


class UnsafeXmlError(ValueError):
    """Raised when XML contains a DTD / external entity (a possible XXE)."""


def sanitize_archive_member(member_name: str) -> str:
    """Return a normalized, root-relative member path or reject it.

    Rejects absolute paths, Windows drive / UNC prefixes, and any path that,
    once normalized, still tries to climb above the extraction root via ``..``.
    The returned value is a clean POSIX-relative path safe to join under a
    controlled destination directory.
    """
    if member_name in ("", ".", ".."):
        raise UnsafeArchiveMemberError(f"empty or dot archive member: {member_name!r}")

    # Normalize separators; zip stores POSIX-style names but be defensive.
    name = member_name.replace("\\", "/")

    # Absolute POSIX path, Windows drive letter (``C:``), or UNC (``//host``).
    if name.startswith("/") or name.startswith("//"):
        raise UnsafeArchiveMemberError(f"absolute archive member: {member_name!r}")
    if len(name) >= 2 and name[1] == ":":
        raise UnsafeArchiveMemberError(f"drive-qualified archive member: {member_name!r}")

    normalized = posixpath.normpath(name)
    if normalized.startswith("/") or normalized == ".." or normalized.startswith("../"):
        raise UnsafeArchiveMemberError(f"path traversal in archive member: {member_name!r}")
    if any(part == ".." for part in PurePosixPath(normalized).parts):
        raise UnsafeArchiveMemberError(f"path traversal in archive member: {member_name!r}")
    return normalized


def safe_parse_xml(data: bytes | str) -> Any:
    """Parse XML from bytes/str with DTDs and entities forbidden.

    Raises :class:`UnsafeXmlError` if the payload declares a DTD or any entity
    (the vectors used for XML external-entity attacks). Returns the parsed
    ``ElementTree`` root element otherwise.
    """
    try:
        return _defused_fromstring(
            data,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except Exception as exc:
        raise UnsafeXmlError(f"unsafe or invalid XML rejected: {exc}") from exc


def safe_parse_xml_file(path: str) -> Any:
    """Parse an XML *file* with DTDs and entities forbidden (see :func:`safe_parse_xml`)."""
    try:
        tree = _defused_parse(
            path,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except Exception as exc:
        raise UnsafeXmlError(f"unsafe or invalid XML rejected: {exc}") from exc
    return tree.getroot()


def looks_like_xml(head: bytes) -> bool:
    """Heuristic: does this byte prefix look like XML (and thus a possible XXE)?"""
    stripped = head.lstrip()
    return stripped.startswith(b"<?xml") or b"<!DOCTYPE" in head or b"<!ENTITY" in head
