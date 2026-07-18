"""In-memory store for uploads and the permanent upload history.

Holds each upload's metadata, the parsed proposed payloads (per config id), the
computed diff, and lifecycle status. History is append-only and never mutated
destructively — it is the audit-facing record of every upload.
"""In-memory upload registry + background parse execution.

Holds one :class:`UploadRecord` per uploaded file, persists the bytes to the
sandbox scratch directory, and runs parse jobs on a small thread pool. Each
parse job invokes :func:`app.worker.run_parse_job`, which spawns the actual
hardened, network-isolated child process — so a crashed or timed-out worker only
fails its own job and never affects the API process.

This is deliberately in-memory: the ingest service is stateless decision-support
and holds no canonical or customer data of record. Nothing here writes to the
canonical model or to any control system.
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
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from canonical_water_model import now_iso

from .models import UploadStatus
from .parsers import ParseResult, ParseScope, ParseStatus
from .proposal import ChangeProposal
from .reconciler import ReconcileResult
from .worker import run_parse_job


@dataclass
class UploadRecord:
    """The mutable state of a single uploaded file."""

    upload_id: str
    filename: str
    path: str
    size_bytes: int
    created_at: str
    updated_at: str
    status: UploadStatus = UploadStatus.received
    sniffed_format: str | None = None
    scope: ParseScope | None = None
    classified: bool = False
    error: str | None = None
    parse_result: ParseResult | None = None
    reconcile_result: ReconcileResult | None = None
    proposal: ChangeProposal | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class UploadStore:
    """Registry + background executor for uploads (thread-safe)."""

    def __init__(
        self,
        *,
        scratch_dir: str,
        timeout_s: float,
        memory_mb: int,
        max_fsize_bytes: int,
        allow_root: bool = False,
        max_workers: int = 2,
    ) -> None:
        self._scratch_dir = scratch_dir
        self._timeout_s = timeout_s
        self._memory_mb = memory_mb
        self._max_fsize_bytes = max_fsize_bytes
        self._allow_root = allow_root
        self._records: dict[str, UploadRecord] = {}
        self._guard = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        os.makedirs(scratch_dir, exist_ok=True)

    def create(self, filename: str, content: bytes, sniffed_format: str | None) -> UploadRecord:
        upload_id = uuid.uuid4().hex
        safe_name = os.path.basename(filename) or "upload.inp"
        path = os.path.join(self._scratch_dir, f"{upload_id}__{safe_name}")
        with open(path, "wb") as handle:
            handle.write(content)
        now = now_iso()
        record = UploadRecord(
            upload_id=upload_id,
            filename=safe_name,
            path=path,
            size_bytes=len(content),
            created_at=now,
            updated_at=now,
            sniffed_format=sniffed_format,
        )
        with self._guard:
            self._records[upload_id] = record
        return record

    def get(self, upload_id: str) -> UploadRecord | None:
        with self._guard:
            return self._records.get(upload_id)

    def classify(self, record: UploadRecord, scope: ParseScope) -> None:
        with record.lock:
            record.scope = scope
            record.classified = True
            record.status = UploadStatus.classified
            record.updated_at = now_iso()

    def enqueue_parse(self, record: UploadRecord) -> None:
        with record.lock:
            record.status = UploadStatus.queued
            record.parse_result = None
            record.reconcile_result = None
            record.proposal = None
            record.error = None
            record.updated_at = now_iso()
        self._executor.submit(self._run_parse, record)

    def _run_parse(self, record: UploadRecord) -> None:
        with record.lock:
            record.status = UploadStatus.parsing
            record.updated_at = now_iso()
            scope = record.scope
            path = record.path
        assert scope is not None  # enqueue is gated on a confirmed classification
        result = run_parse_job(
            path,
            scope,
            timeout_s=self._timeout_s,
            memory_mb=self._memory_mb,
            scratch_dir=self._scratch_dir,
            max_fsize_bytes=self._max_fsize_bytes,
            allow_root=self._allow_root,
        )
        with record.lock:
            record.parse_result = result
            record.updated_at = now_iso()
            if result.status is ParseStatus.parse_failed:
                record.status = UploadStatus.parse_failed
                record.error = result.error
            elif result.status is ParseStatus.partial:
                record.status = UploadStatus.partial
            else:
                record.status = UploadStatus.parsed

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
