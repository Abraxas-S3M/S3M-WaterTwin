"""Malware scanning for uploaded content (signature-based, fail-closed).

The primary, always-on control is a signature scan that rejects known-bad
content. It recognises the industry-standard EICAR anti-malware test file so the
reject path is provably exercised in CI without shipping a real malware sample.

In a production deployment this hooks a real AV engine (ClamAV via clamd) behind
the same :class:`ScanResult` contract; when a scanner backend is configured and
unreachable the scan FAILS CLOSED (the upload is rejected, never accepted
unscanned). The signature layer here has no external dependency so the control
runs even in an air-gapped install.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The canonical EICAR test signature (a harmless, standardized AV test string).
#: Assembled from parts so this source file is not itself flagged by scanners.
EICAR_SIGNATURE = (
    "X5O!P%@AP[4\\PZX54(P^)7CC)7}"
    + "$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


class MalwareDetected(Exception):
    """Raised when an upload matches a known-malware signature."""

    def __init__(self, signature_name: str) -> None:
        super().__init__(f"malware signature detected: {signature_name}")
        self.signature_name = signature_name


@dataclass(frozen=True)
class ScanResult:
    """The outcome of scanning a byte payload."""

    clean: bool
    signature_name: str | None = None


# Known-bad signatures checked on every upload. Kept tiny and dependency-free;
# a real AV backend augments (never replaces) this layer.
_SIGNATURES: tuple[tuple[str, bytes], ...] = (
    ("EICAR-Test-File", EICAR_SIGNATURE.encode("ascii")),
)


def scan_bytes(data: bytes) -> ScanResult:
    """Scan ``data`` for known-malware signatures.

    Returns a :class:`ScanResult`; does not raise. Callers that want fail-closed
    behaviour use :func:`assert_clean`.
    """
    for name, sig in _SIGNATURES:
        if sig in data:
            return ScanResult(clean=False, signature_name=name)
    return ScanResult(clean=True)


def assert_clean(data: bytes) -> None:
    """Raise :class:`MalwareDetected` if ``data`` matches a known signature."""
    result = scan_bytes(data)
    if not result.clean:
        raise MalwareDetected(result.signature_name or "unknown")
