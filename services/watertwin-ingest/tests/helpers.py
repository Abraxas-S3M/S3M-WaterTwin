"""Shared helpers for building upload payloads in the ingest test-suite."""

from __future__ import annotations

import io
import zipfile


def make_zip(members: dict[str, bytes], *, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    """Build an in-memory zip from ``{name: bytes}`` and return its bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def make_zip_with_unsafe_member(name: str, data: bytes = b"payload") -> bytes:
    """Build a zip whose single member has an unsafe (traversal/absolute) name."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo(filename=name)
        zf.writestr(info, data)
    return buf.getvalue()


def upload(client, *, filename, content, content_type, declared_class="generic",
           facility_id="S3M-DESAL-01", headers=None):
    """POST a multipart upload to the ingest endpoint."""
    return client.post(
        "/api/v1/ingest/uploads",
        headers=headers,
        files={"file": (filename, content, content_type)},
        data={"facility_id": facility_id, "declared_class": declared_class},
    )
