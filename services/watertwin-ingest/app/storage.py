"""Content-addressed, WRITE-ONCE staging store for received files.

Design invariants:

* **Never load a whole file into memory.** Uploads are streamed to disk in
  bounded chunks (:class:`StagingWriter`); the ``sha256`` is computed *during*
  streaming, not in a second pass.
* **Content-addressed.** The immutable key is
  ``{tenant_id}/{yyyy}/{mm}/{sha256}`` so identical bytes deduplicate and the
  address is verifiable.
* **Write-once.** There is no update or overwrite path. A committed object is
  made read-only; a second commit of the same address is a no-op dedup. New
  content supersedes old only by producing a *new* record (superseding is a
  lifecycle concern, not a storage mutation).
* **Backend abstraction.** A local-filesystem backend is implemented now; an
  S3-compatible backend is stubbed behind the same interface.

Nothing here reaches OT or a control system; it only reads the inbound byte
stream and writes it to the staging store.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import BinaryIO

from . import config

#: Bytes of the leading content retained for the magic-byte sniff.
HEADER_BYTES = 512


class StorageError(RuntimeError):
    """Base class for storage failures."""


class OversizeError(StorageError):
    """Raised while streaming when the size cap for the declared class is exceeded.

    Raised *before* the object is committed to the store, so an oversize upload
    is rejected pre-storage and leaves nothing behind.
    """

    def __init__(self, size_cap: int) -> None:
        super().__init__(f"file exceeds the size cap of {size_cap} bytes for its declared class")
        self.size_cap = size_cap


@dataclass
class StagedFile:
    """A fully-streamed staging file, not yet committed to the content store."""

    temp_path: str
    sha256: str
    size_bytes: int
    header: bytes

    def open(self) -> BinaryIO:
        """Open the staged bytes read-only (used by the scanner, e.g. zip checks)."""
        return open(self.temp_path, "rb")

    def discard(self) -> None:
        """Delete the staging file (rejected upload / after a successful commit)."""
        try:
            os.remove(self.temp_path)
        except FileNotFoundError:
            pass


@dataclass
class StoredObject:
    """A committed, content-addressed object in the write-once store."""

    key: str
    sha256: str
    size_bytes: int
    backend: str
    deduplicated: bool = False


@dataclass
class StagingWriter:
    """Streams inbound chunks to a temp file, hashing + size-capping as it goes."""

    staging_dir: str
    size_cap: int
    _hasher: "hashlib._Hash" = field(init=False)
    _size: int = field(init=False, default=0)
    _header: bytearray = field(init=False)
    _fh: BinaryIO = field(init=False)
    _temp_path: str = field(init=False)

    def __post_init__(self) -> None:
        os.makedirs(self.staging_dir, exist_ok=True)
        fd, self._temp_path = tempfile.mkstemp(dir=self.staging_dir, prefix="staging-")
        self._fh = os.fdopen(fd, "wb")
        self._hasher = hashlib.sha256()
        self._header = bytearray()

    def write(self, chunk: bytes) -> None:
        """Append ``chunk``; raise :class:`OversizeError` past the size cap."""
        if not chunk:
            return
        self._size += len(chunk)
        if self._size > self.size_cap:
            self._abort()
            raise OversizeError(self.size_cap)
        self._hasher.update(chunk)
        if len(self._header) < HEADER_BYTES:
            self._header.extend(chunk[: HEADER_BYTES - len(self._header)])
        self._fh.write(chunk)

    def _abort(self) -> None:
        try:
            self._fh.close()
        finally:
            try:
                os.remove(self._temp_path)
            except FileNotFoundError:
                pass

    def finish(self) -> StagedFile:
        """Close the temp file and return the :class:`StagedFile` handle."""
        self._fh.close()
        return StagedFile(
            temp_path=self._temp_path,
            sha256=self._hasher.hexdigest(),
            size_bytes=self._size,
            header=bytes(self._header),
        )


def _content_key(tenant_id: str, sha256: str, when: datetime | None = None) -> str:
    when = when or datetime.now(UTC)
    return f"{tenant_id}/{when:%Y}/{when:%m}/{sha256}"


class StorageBackend(ABC):
    """Backend interface for the write-once content store."""

    name: str

    @abstractmethod
    def staging_dir(self) -> str:
        """Return a directory on the same volume as committed objects (for atomicity)."""

    @abstractmethod
    def commit(self, staged: StagedFile, tenant_id: str) -> StoredObject:
        """Move ``staged`` into its content-addressed key (write-once)."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Whether a committed object exists at ``key``."""

    @abstractmethod
    def open(self, key: str) -> BinaryIO:
        """Open a committed object read-only for streaming back to an admin."""

    def new_writer(self, size_cap: int) -> StagingWriter:
        """Create a :class:`StagingWriter` bound to this backend's staging dir."""
        return StagingWriter(staging_dir=self.staging_dir(), size_cap=size_cap)


class LocalFilesystemBackend(StorageBackend):
    """Local-filesystem implementation of the write-once content store."""

    name = "local"

    def __init__(self, root: str) -> None:
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def staging_dir(self) -> str:
        return os.path.join(self.root, ".staging")

    def _abs(self, key: str) -> str:
        return os.path.join(self.root, key)

    def exists(self, key: str) -> bool:
        return os.path.exists(self._abs(key))

    def commit(self, staged: StagedFile, tenant_id: str) -> StoredObject:
        key = _content_key(tenant_id, staged.sha256)
        target = self._abs(key)
        if os.path.exists(target):
            # Write-once dedup: identical content already stored. Never overwrite.
            staged.discard()
            return StoredObject(
                key=key,
                sha256=staged.sha256,
                size_bytes=staged.size_bytes,
                backend=self.name,
                deduplicated=True,
            )
        os.makedirs(os.path.dirname(target), exist_ok=True)
        # Atomic publish (same filesystem), then drop write permission to make
        # the object immutable at the filesystem layer too.
        os.replace(staged.temp_path, target)
        try:
            os.chmod(target, 0o444)
        except OSError:  # pragma: no cover - platform dependent
            pass
        return StoredObject(
            key=key, sha256=staged.sha256, size_bytes=staged.size_bytes, backend=self.name
        )

    def open(self, key: str) -> BinaryIO:
        return open(self._abs(key), "rb")


class S3CompatibleBackend(StorageBackend):
    """S3-compatible backend, stubbed behind the same interface.

    A real implementation would multipart-upload the staged file to an
    object-store bucket under the same ``{tenant_id}/{yyyy}/{mm}/{sha256}`` key,
    relying on the store's write-once / object-lock semantics. It is stubbed
    here so the abstraction and wiring exist without pulling an SDK dependency
    into this PR.
    """

    name = "s3"

    def __init__(self, *, bucket: str | None, endpoint: str | None, prefix: str = "") -> None:
        self.bucket = bucket
        self.endpoint = endpoint
        self.prefix = prefix

    def staging_dir(self) -> str:
        return os.path.join(tempfile.gettempdir(), "watertwin-ingest-s3-staging")

    def _unavailable(self) -> StorageError:
        return StorageError(
            "S3-compatible storage backend is not implemented in this build; "
            "set INGEST_STORAGE_BACKEND=local or provide an S3 implementation."
        )

    def commit(self, staged: StagedFile, tenant_id: str) -> StoredObject:
        raise self._unavailable()

    def exists(self, key: str) -> bool:
        raise self._unavailable()

    def open(self, key: str) -> BinaryIO:
        raise self._unavailable()


def build_backend() -> StorageBackend:
    """Construct the configured storage backend."""
    if config.STORAGE_BACKEND == "s3":
        return S3CompatibleBackend(
            bucket=config.STORAGE_S3_BUCKET,
            endpoint=config.STORAGE_S3_ENDPOINT,
            prefix=config.STORAGE_S3_PREFIX,
        )
    return LocalFilesystemBackend(config.STORAGE_ROOT)


def iter_file(fh: BinaryIO, chunk_size: int) -> Iterator[bytes]:
    """Yield ``chunk_size`` byte chunks from ``fh`` then close it."""
    try:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        fh.close()
