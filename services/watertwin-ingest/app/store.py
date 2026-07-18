"""In-memory store for uploads and the permanent upload history.

Holds each upload's metadata, the parsed proposed payloads (per config id), the
computed diff, and lifecycle status. History is append-only and never mutated
destructively — it is the audit-facing record of every upload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import IngestClass, IngestDiffGroup, IngestEntityCount, IngestUnparsedRow


@dataclass
class Upload:
    upload_id: str
    filename: str
    sha256: str
    size_bytes: int
    uploader: str
    timestamp: str
    upload_class: IngestClass
    status: str = "classified"
    content: str = ""
    # Full proposed payload per (entity, config_id), used to create drafts on
    # submit (config versions are whole-object).
    payloads: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    diff: list[IngestDiffGroup] = field(default_factory=list)
    entity_counts: list[IngestEntityCount] = field(default_factory=list)
    unparsed: list[IngestUnparsedRow] = field(default_factory=list)
    config_version: int | None = None
    approver: str | None = None
    submitter: str | None = None


class IngestStore:
    def __init__(self) -> None:
        self._uploads: dict[str, Upload] = {}

    def put(self, upload: Upload) -> None:
        self._uploads[upload.upload_id] = upload

    def get(self, upload_id: str) -> Upload | None:
        return self._uploads.get(upload_id)

    def all(self) -> list[Upload]:
        # Newest first for the history view.
        return sorted(self._uploads.values(), key=lambda u: u.timestamp, reverse=True)

    def reset(self) -> None:
        self._uploads.clear()
