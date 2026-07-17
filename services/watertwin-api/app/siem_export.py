"""Signed, append-only SIEM export of the immutable audit log.

Produces a machine-ingestible export of the tamper-evident audit hash-chain
(see :mod:`app.audit`) in two formats a SIEM can consume:

* **JSON** — the ordered chain (oldest-first) plus the chain head, the live
  verify status, and a detached HMAC-SHA256 signature over the canonical record
  bytes. The export is *append-only*: it mirrors the append-only audit trail and
  never mutates or reorders events.
* **CEF** — one ArcSight Common Event Format line per event, oldest-first, with a
  trailing signature line binding the whole batch.

The signature lets a downstream SIEM detect any tampering with, reordering of,
or truncation of the exported records independently of the in-band hash chain.
The signing key comes from ``WATERTWIN_SIEM_HMAC_KEY`` (a documented dev default
is used otherwise). This module is pure and side-effect free; it reads the audit
log and writes nothing — there is no control path.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime
from typing import Any

from . import audit as audit_chain

SIGNATURE_ALG = "HMAC-SHA256"
CEF_VERSION = 0
CEF_VENDOR = "S3M"
CEF_PRODUCT = "WaterTwin"
CEF_DEVICE_VERSION = "1.0"

#: Explicit, documented dev signing key. Production deployments MUST override it
#: with a real secret via ``WATERTWIN_SIEM_HMAC_KEY``.
_DEFAULT_KEY = "watertwin-dev-siem-signing-key"

#: Ordered fields exported per record (kept stable so signatures are portable).
_RECORD_FIELDS = ("id", "ts", "kind", "actor", "subject", "payload", "prev_hash", "hash")


def signing_key() -> bytes:
    key = os.environ.get("WATERTWIN_SIEM_HMAC_KEY", "").strip() or _DEFAULT_KEY
    return key.encode("utf-8")


def _record(event: dict[str, Any], seq: int) -> dict[str, Any]:
    rec = {field: event.get(field) for field in _RECORD_FIELDS}
    rec["seq"] = seq
    return rec


def _records(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the ordered (oldest-first) export records with a 1-based seq."""
    return [_record(event, i + 1) for i, event in enumerate(events)]


def sign(records: list[dict[str, Any]], head: str) -> str:
    """Detached HMAC-SHA256 over the canonical record bytes + chain head.

    Because the canonical encoding includes every field of every record in
    order, any edit, reorder, insertion or truncation changes the signature.
    """
    material = audit_chain.canonical({"records": records, "head": head})
    return hmac.new(signing_key(), material.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(records: list[dict[str, Any]], head: str, signature: str) -> bool:
    """Constant-time check that ``signature`` matches ``records`` + ``head``."""
    return hmac.compare_digest(sign(records, head), signature)


def build_json_export(
    events: list[dict[str, Any]], verify_result: dict[str, Any]
) -> dict[str, Any]:
    """Build the signed, append-only JSON SIEM export.

    Args:
        events: The audit chain oldest-first (as returned by
            :meth:`app.store.Store.audit_chain_asc`).
        verify_result: The chain verify status
            (:meth:`app.store.Store.verify_chain`).
    """
    records = _records(events)
    head = verify_result.get("head") or (records[-1]["hash"] if records else audit_chain.GENESIS_HASH)
    signature = sign(records, head)
    return {
        "export_format": "json",
        "source": "s3m-watertwin",
        "generated_at": datetime.now(UTC).isoformat(),
        "append_only": True,
        "record_count": len(records),
        "chain": {
            "verified": bool(verify_result.get("ok")),
            "head": head,
            "verify": verify_result,
        },
        "records": records,
        "signature": {
            "alg": SIGNATURE_ALG,
            "value": signature,
            "signed_fields": list(_RECORD_FIELDS) + ["seq"],
            "detail": "HMAC-SHA256 over canonical({records, head})",
        },
    }


# --------------------------------------------------------------------------- #
# CEF
# --------------------------------------------------------------------------- #

_CEF_ESCAPE_HEADER = str.maketrans({"\\": "\\\\", "|": "\\|", "\n": " "})


def _cef_header(value: Any) -> str:
    return str(value if value is not None else "").translate(_CEF_ESCAPE_HEADER)


def _cef_ext(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("\\", "\\\\").replace("=", "\\=").replace("\n", " ")


#: Advisory severities per audit event-kind family (0-10 CEF scale).
def _severity(kind: str) -> int:
    if kind.startswith("system.reset"):
        return 6
    if "decision" in kind:
        return 5
    if "alert" in kind:
        return 5
    if "recommendation" in kind:
        return 4
    return 3


def _cef_line(record: dict[str, Any]) -> str:
    kind = record.get("kind") or "audit.event"
    header = (
        f"CEF:{CEF_VERSION}|{_cef_header(CEF_VENDOR)}|{_cef_header(CEF_PRODUCT)}|"
        f"{_cef_header(CEF_DEVICE_VERSION)}|{_cef_header(kind)}|{_cef_header(kind)}|"
        f"{_severity(kind)}"
    )
    ext_pairs = [
        ("rt", record.get("ts")),
        ("externalId", record.get("id")),
        ("suser", record.get("actor")),
        ("cn1", record.get("seq")),
        ("cn1Label", "seq"),
        ("cs1", record.get("hash")),
        ("cs1Label", "hash"),
        ("cs2", record.get("prev_hash")),
        ("cs2Label", "prev_hash"),
        ("cs3", record.get("subject")),
        ("cs3Label", "subject"),
        ("cs4", audit_chain.canonical(record.get("payload") or {})),
        ("cs4Label", "payload"),
    ]
    ext = " ".join(f"{k}={_cef_ext(v)}" for k, v in ext_pairs)
    return f"{header}|{ext}"


def build_cef_export(
    events: list[dict[str, Any]], verify_result: dict[str, Any]
) -> str:
    """Build the signed, append-only CEF SIEM export (oldest-first).

    Comment header lines carry the export metadata + verify status; each event
    is one CEF line in chain order; a trailing ``#signature`` line binds the
    batch (same HMAC as the JSON export).
    """
    records = _records(events)
    head = verify_result.get("head") or (records[-1]["hash"] if records else audit_chain.GENESIS_HASH)
    signature = sign(records, head)
    lines = [
        "# S3M-WaterTwin SIEM export (CEF)",
        f"# generated_at={datetime.now(UTC).isoformat()}",
        f"# append_only=true record_count={len(records)}",
        f"# chain_verified={str(bool(verify_result.get('ok'))).lower()} chain_head={head}",
    ]
    lines.extend(_cef_line(rec) for rec in records)
    lines.append(f"#signature alg={SIGNATURE_ALG} value={signature}")
    return "\n".join(lines) + "\n"
