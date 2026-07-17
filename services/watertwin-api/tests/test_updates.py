"""Signed-update channel tests: signature verification (verify-before-apply).

The update channel only *verifies* a signed manifest; it never applies one.
These tests generate a local Ed25519 key, sign a manifest, and prove that a
valid signature verifies while tampering (of the manifest or the signature) is
rejected — and that verification never reports an applied update.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app import updates
from app.main import app


@pytest.fixture(scope="module")
def keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv, pub, pem


MANIFEST = {
    "version": "0.2.0",
    "channel": "stable",
    "released_at": "2026-07-01T00:00:00Z",
    "artifact": "s3m-watertwin/watertwin-api:0.2.0",
    "sha256": "0" * 64,
}


def _sign(priv: Ed25519PrivateKey, manifest: dict) -> str:
    return priv.sign(updates.canonical_manifest_bytes(manifest)).hex()


# --- Pure verification ------------------------------------------------------


def test_valid_signature_verifies(keypair):
    priv, pub, _ = keypair
    result = updates.verify_manifest(MANIFEST, _sign(priv, MANIFEST), public_key=pub)
    assert result["verified"] is True
    assert result["manifest_version"] == "0.2.0"
    # Verification NEVER applies the update.
    assert result["applied"] is False


def test_tampered_manifest_is_rejected(keypair):
    priv, pub, _ = keypair
    signature = _sign(priv, MANIFEST)
    tampered = {**MANIFEST, "artifact": "evil/image:latest"}
    result = updates.verify_manifest(tampered, signature, public_key=pub)
    assert result["verified"] is False
    assert result["applied"] is False


def test_bad_signature_hex_is_rejected(keypair):
    _, pub, _ = keypair
    result = updates.verify_manifest(MANIFEST, "not-hex!!", public_key=pub)
    assert result["verified"] is False
    assert "hex" in result["reason"]


def test_wrong_key_is_rejected(keypair):
    priv, _, _ = keypair
    other_pub = Ed25519PrivateKey.generate().public_key()
    result = updates.verify_manifest(MANIFEST, _sign(priv, MANIFEST), public_key=other_pub)
    assert result["verified"] is False


def test_no_key_configured_reports_missing_key(monkeypatch):
    monkeypatch.delenv("WATERTWIN_UPDATE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("WATERTWIN_UPDATE_PUBLIC_KEY_HEX", raising=False)
    result = updates.verify_manifest(MANIFEST, "00")
    assert result["verified"] is False
    assert "public key" in result["reason"]


def test_pem_and_hex_keys_load_equivalently(keypair):
    priv, pub, pem = keypair
    signature = _sign(priv, MANIFEST)
    raw_hex = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    assert updates.verify_manifest(MANIFEST, signature, key_pem=pem)["verified"] is True
    assert updates.verify_manifest(MANIFEST, signature, key_hex=raw_hex)["verified"] is True


# --- Through the API --------------------------------------------------------


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_channel_info_never_auto_updates(client, monkeypatch, keypair):
    _, _, pem = keypair
    monkeypatch.setenv("WATERTWIN_UPDATE_PUBLIC_KEY", pem)
    info = client.get("/api/v1/admin/update-channel").json()["update_channel"]
    assert info["auto_update_enabled"] is False
    assert info["verify_before_apply"] is True
    assert info["public_key_configured"] is True
    assert info["signature_algorithm"] == "ed25519"


def test_verify_endpoint_verifies_without_applying(client, keypair):
    priv, _, pem = keypair
    resp = client.post(
        "/api/v1/admin/update-channel/verify",
        json={
            "manifest": MANIFEST,
            "signature": _sign(priv, MANIFEST),
            "public_key": pem,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verification"]["verified"] is True
    assert body["applied"] is False
    assert body["control_boundary"]["control_write_enabled"] is False


def test_verify_endpoint_rejects_tampered_manifest(client, keypair):
    priv, _, pem = keypair
    signature = _sign(priv, MANIFEST)
    resp = client.post(
        "/api/v1/admin/update-channel/verify",
        json={
            "manifest": {**MANIFEST, "artifact": "evil/image:latest"},
            "signature": signature,
            "public_key": pem,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["verification"]["verified"] is False
