"""Pre-parse structural validation, run BEFORE anything else reads the file.

The scanner is a purely structural gate (no parsing, no business logic). It:

* enforces a per-declared-class size cap (config-driven; the cap value is
  supplied to the streaming writer so an oversize upload is rejected
  *pre-storage*);
* sniffs the content type from the leading magic bytes and rejects a file whose
  bytes contradict its extension;
* for archives, applies bomb defences computed from archive *metadata* only
  (compression-ratio cap, nesting-depth cap, absolute uncompressed-size cap) and
  rejects any member with a ``..`` traversal or absolute path; and
* runs a pluggable antivirus hook (no-op by default, ClamAV behind a config
  flag) and logs clearly which backend is active.

None of this reaches OT or a control system.
"""

from __future__ import annotations

import logging
import os
import socket
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass

from . import config
from .storage import StagedFile

logger = logging.getLogger("watertwin.ingest.scanner")

# Leading magic-byte signatures -> (mime, category). Order matters (longest /
# most specific first is unnecessary here as prefixes are unambiguous).
_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"%PDF", "application/pdf", "pdf"),
    (b"PK\x03\x04", "application/zip", "zip"),
    (b"PK\x05\x06", "application/zip", "zip"),
    (b"PK\x07\x08", "application/zip", "zip"),
    (b"\x1f\x8b", "application/gzip", "gzip"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpeg"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
]

#: All binary categories that carry a definitive leading signature.
_BINARY_CATEGORIES = frozenset({"pdf", "zip", "gzip", "png", "jpeg", "gif"})

#: Extension -> the categories acceptable for that extension. ``text`` means the
#: file must NOT carry a binary signature (any of :data:`_BINARY_CATEGORIES`).
_EXTENSION_EXPECTATION: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"pdf"}),
    ".zip": frozenset({"zip"}),
    ".xlsx": frozenset({"zip"}),
    ".docx": frozenset({"zip"}),
    ".pptx": frozenset({"zip"}),
    ".gz": frozenset({"gzip"}),
    ".tgz": frozenset({"gzip"}),
    ".png": frozenset({"png"}),
    ".jpg": frozenset({"jpeg"}),
    ".jpeg": frozenset({"jpeg"}),
    ".gif": frozenset({"gif"}),
    ".csv": frozenset({"text"}),
    ".txt": frozenset({"text"}),
    ".json": frozenset({"text"}),
    ".xml": frozenset({"text"}),
    ".inp": frozenset({"text"}),
    ".log": frozenset({"text"}),
    ".tsv": frozenset({"text"}),
}

#: Member extensions that mark a nested archive (for the nesting-depth cap).
_ARCHIVE_EXTENSIONS = frozenset({".zip", ".gz", ".tgz", ".tar", ".7z", ".rar", ".bz2", ".xz"})


class ScanRejected(Exception):
    """A file failed structural validation and must not be stored/processed."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


class ScanError(RuntimeError):
    """A scan could not be completed (e.g. the AV backend is unreachable)."""


@dataclass(frozen=True)
class ScanOutcome:
    """The structural facts the scanner determined about a file."""

    content_type_detected: str
    detected_class: str


def size_cap_for(declared_class: str) -> int:
    """Return the byte size cap for ``declared_class`` (config-driven)."""
    return config.size_cap_for(declared_class)


def sniff(header: bytes) -> tuple[str, str]:
    """Return ``(mime, category)`` sniffed from the leading bytes.

    Falls back to ``("application/octet-stream", "unknown")`` when no known
    signature matches (the file has no definitive binary signature).
    """
    for signature, mime, category in _SIGNATURES:
        if header.startswith(signature):
            return mime, category
    return "application/octet-stream", "unknown"


def _extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def _check_content_type(filename: str, header: bytes) -> tuple[str, str]:
    """Sniff the content type and reject when it contradicts the extension.

    Returns ``(content_type_detected, detected_class)``.
    """
    mime, category = sniff(header)
    ext = _extension(filename)
    expected = _EXTENSION_EXPECTATION.get(ext)
    if expected is None:
        # Unknown extension: nothing to contradict.
        return mime, category
    if "text" in expected:
        # A text-ish extension must not carry a binary signature.
        if category in _BINARY_CATEGORIES:
            raise ScanRejected(
                "content_type_mismatch",
                f"file extension {ext!r} implies a text file but the bytes are "
                f"{mime} ({category}); refusing the upload",
            )
        return mime, "text"
    # A binary-signature extension: the sniffed category must match exactly.
    if category not in expected:
        raise ScanRejected(
            "content_type_mismatch",
            f"file extension {ext!r} implies {sorted(expected)} but the bytes "
            f"sniffed as {mime} ({category}); refusing the upload",
        )
    return mime, category


def _is_unsafe_member(name: str) -> bool:
    """True if an archive member name would escape the extraction root."""
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or os.path.isabs(normalized):
        return True
    # Any path component that is exactly ``..`` is a traversal.
    return any(part == ".." for part in normalized.split("/"))


def _check_archive(staged: StagedFile) -> None:
    """Apply zip-bomb defences from archive metadata only (never extracts)."""
    if not zipfile.is_zipfile(staged.temp_path):
        return
    total_uncompressed = 0
    total_compressed = 0
    nested_archives = 0
    with zipfile.ZipFile(staged.temp_path) as zf:
        for info in zf.infolist():
            if _is_unsafe_member(info.filename):
                raise ScanRejected(
                    "archive_unsafe_path",
                    f"archive member {info.filename!r} uses an absolute path or a "
                    "'..' traversal; refusing the upload",
                )
            total_uncompressed += info.file_size
            total_compressed += info.compress_size
            if _extension(info.filename) in _ARCHIVE_EXTENSIONS:
                nested_archives += 1

    if total_uncompressed > config.ARCHIVE_MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise ScanRejected(
            "archive_size",
            f"archive expands to {total_uncompressed} bytes, over the "
            f"{config.ARCHIVE_MAX_TOTAL_UNCOMPRESSED_BYTES}-byte uncompressed cap",
        )
    ratio = total_uncompressed / max(total_compressed, 1)
    if ratio > config.ARCHIVE_MAX_COMPRESSION_RATIO:
        raise ScanRejected(
            "archive_ratio",
            f"archive compression ratio {ratio:.1f}:1 exceeds the "
            f"{config.ARCHIVE_MAX_COMPRESSION_RATIO:.0f}:1 cap",
        )
    if nested_archives > config.ARCHIVE_MAX_NESTING_DEPTH:
        raise ScanRejected(
            "archive_depth",
            f"archive nests {nested_archives} further archive(s), over the "
            f"{config.ARCHIVE_MAX_NESTING_DEPTH} nesting-depth cap",
        )


# --------------------------------------------------------------------------- #
# Antivirus hook (pluggable; no-op default, ClamAV behind a config flag).
# --------------------------------------------------------------------------- #


class AntivirusScanner(ABC):
    """Pluggable antivirus interface."""

    name: str

    @abstractmethod
    def scan(self, staged: StagedFile) -> None:
        """Raise :class:`ScanRejected` (code ``malware``) if the file is infected."""


class NoOpAntivirus(AntivirusScanner):
    """Default: performs no scanning (explicitly logged at startup)."""

    name = "noop"

    def scan(self, staged: StagedFile) -> None:
        return None


class ClamAVAntivirus(AntivirusScanner):
    """Streams the staged file to a ClamAV ``clamd`` daemon (INSTREAM), fail-closed."""

    name = "clamav"

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def scan(self, staged: StagedFile) -> None:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.sendall(b"zINSTREAM\x00")
                with staged.open() as fh:
                    while True:
                        chunk = fh.read(config.STREAM_CHUNK_BYTES)
                        if not chunk:
                            break
                        sock.sendall(len(chunk).to_bytes(4, "big") + chunk)
                sock.sendall(b"\x00\x00\x00\x00")
                response = sock.recv(4096).decode("utf-8", "replace").strip()
        except OSError as exc:  # fail-closed: an AV we cannot run must not pass
            raise ScanError(f"ClamAV scan could not be completed: {exc}") from exc
        if "FOUND" in response:
            raise ScanRejected("malware", f"antivirus flagged the file: {response}")


def build_antivirus() -> AntivirusScanner:
    """Construct the configured antivirus backend and log which one is active."""
    if config.ANTIVIRUS_BACKEND == "clamav":
        logger.info(
            "antivirus ACTIVE: ClamAV (clamd at %s:%s)", config.CLAMAV_HOST, config.CLAMAV_PORT
        )
        return ClamAVAntivirus(config.CLAMAV_HOST, config.CLAMAV_PORT, config.CLAMAV_TIMEOUT_S)
    logger.info("antivirus INACTIVE: no-op scanner (INGEST_ANTIVIRUS=noop)")
    return NoOpAntivirus()


def scan(
    staged: StagedFile,
    *,
    filename: str,
    declared_class: str,
    antivirus: AntivirusScanner,
) -> ScanOutcome:
    """Run the full structural scan on a staged file.

    Raises :class:`ScanRejected` on any structural failure. Returns the detected
    content type + class on success. Size-cap enforcement happens during
    streaming (the writer is created with :func:`size_cap_for`), so by the time
    this runs the file is already within its declared-class cap.
    """
    content_type_detected, detected_class = _check_content_type(filename, staged.header)
    _check_archive(staged)
    antivirus.scan(staged)
    return ScanOutcome(content_type_detected=content_type_detected, detected_class=detected_class)
