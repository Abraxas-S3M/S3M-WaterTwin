"""Signed-update channel reference.

Commercial-hardening work package: a **signed-update channel**. This module is
a *reference* for how a WaterTwin deployment learns about, and cryptographically
verifies, a new release before it is applied.

Hard rules (documented and enforced by the API surface):

* **Verify before apply.** An update manifest is only trustworthy once its
  Ed25519 signature is verified against the deployment's configured release
  public key. :func:`verify_manifest` performs that check.
* **Never auto-update in production.** This service does **not** download,
  unpack, or apply updates. Applying a verified update is an out-of-band,
  operator-driven action (roll the container image / redeploy). The API only
  *reports* channel status and *verifies* a supplied manifest signature; it has
  no code path that mutates the running deployment.

Signature scheme: Ed25519 over the canonical JSON encoding of the manifest
(sorted keys, no insignificant whitespace). The release public key is supplied
via ``WATERTWIN_UPDATE_PUBLIC_KEY`` (PEM) or ``WATERTWIN_UPDATE_PUBLIC_KEY_HEX``
(32-byte raw key, hex-encoded).
"""

from __future__ import annotations

import binascii
import hashlib
import json
import logging
import os
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import config

logger = logging.getLogger("watertwin.updates")

SIGNATURE_ALGORITHM = "ed25519"


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def update_channel() -> str:
    return _env("WATERTWIN_UPDATE_CHANNEL") or "stable"


def canonical_manifest_bytes(manifest: dict) -> bytes:
    """Deterministic bytes signed/verified for a manifest."""
    return json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def load_public_key(
    *, pem: Optional[str] = None, hex_key: Optional[str] = None
) -> Optional[Ed25519PublicKey]:
    """Load the release public key from a PEM or a raw hex-encoded key.

    Falls back to the environment (``WATERTWIN_UPDATE_PUBLIC_KEY`` /
    ``WATERTWIN_UPDATE_PUBLIC_KEY_HEX``) when neither argument is given.
    """
    pem = pem or _env("WATERTWIN_UPDATE_PUBLIC_KEY")
    hex_key = hex_key or _env("WATERTWIN_UPDATE_PUBLIC_KEY_HEX")

    if pem:
        try:
            key = serialization.load_pem_public_key(pem.encode("utf-8"))
            if isinstance(key, Ed25519PublicKey):
                return key
            logger.warning("configured update public key is not Ed25519")
            return None
        except (ValueError, TypeError) as exc:
            logger.warning("failed to load PEM update public key", extra={"error": str(exc)})
            return None

    if hex_key:
        try:
            return Ed25519PublicKey.from_public_bytes(bytes.fromhex(hex_key))
        except (ValueError, binascii.Error) as exc:
            logger.warning("failed to load hex update public key", extra={"error": str(exc)})
            return None

    return None


def public_key_fingerprint(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def verify_manifest(
    manifest: dict,
    signature: str,
    *,
    public_key: Optional[Ed25519PublicKey] = None,
    key_pem: Optional[str] = None,
    key_hex: Optional[str] = None,
) -> dict:
    """Verify a manifest's Ed25519 signature.

    ``signature`` is hex-encoded. Returns a structured result; **verification
    never applies the update** — it only reports whether the manifest is
    authentic. The caller is responsible for the out-of-band, operator-driven
    apply step (this service performs none).
    """
    key = public_key or load_public_key(pem=key_pem, hex_key=key_hex)
    if key is None:
        return {
            "verified": False,
            "reason": "no release public key configured (set WATERTWIN_UPDATE_PUBLIC_KEY)",
            "algorithm": SIGNATURE_ALGORITHM,
            "applied": False,
        }

    try:
        sig_bytes = bytes.fromhex(signature)
    except (ValueError, TypeError):
        return {
            "verified": False,
            "reason": "signature is not valid hex",
            "algorithm": SIGNATURE_ALGORITHM,
            "applied": False,
        }

    try:
        key.verify(sig_bytes, canonical_manifest_bytes(manifest))
    except InvalidSignature:
        return {
            "verified": False,
            "reason": "signature does not match the manifest",
            "algorithm": SIGNATURE_ALGORITHM,
            "fingerprint": public_key_fingerprint(key),
            "applied": False,
        }

    return {
        "verified": True,
        "reason": "signature is valid",
        "algorithm": SIGNATURE_ALGORITHM,
        "fingerprint": public_key_fingerprint(key),
        "manifest_version": manifest.get("version"),
        # This reference implementation never applies an update automatically.
        "applied": False,
    }


def channel_info() -> dict:
    """Describe the signed-update channel for the Administration UI."""
    key = load_public_key()
    return {
        "current_version": config.SERVICE_VERSION,
        "channel": update_channel(),
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "public_key_configured": key is not None,
        "public_key_fingerprint": public_key_fingerprint(key) if key else None,
        # The two non-negotiables of the channel policy.
        "auto_update_enabled": False,
        "verify_before_apply": True,
        "policy": (
            "Updates are verified (Ed25519 over the canonical manifest) before "
            "they may be applied, and are applied manually by an operator via a "
            "redeploy — never downloaded or applied automatically in production. "
            "This service only reports channel status and verifies a supplied "
            "manifest signature; it has no code path that mutates the deployment."
        ),
        "documentation": "docs/operations/signed-updates.md",
    }


__all__ = [
    "SIGNATURE_ALGORITHM",
    "canonical_manifest_bytes",
    "channel_info",
    "load_public_key",
    "public_key_fingerprint",
    "update_channel",
    "verify_manifest",
]
