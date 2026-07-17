"""Support-bundle tests: redaction (assert no secrets).

The support bundle must never carry credentials. These tests exercise the
redaction helpers directly and assert end-to-end that a generated bundle
contains none of the seeded secret values (env secrets, URL credentials, or
secrets that leaked into a log line).

Secret values here are assembled at runtime from fragments so the test source
itself never contains a literal secret (keeps the repo secret-scanner quiet).
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import log_buffer, support
from app.main import app
from app.support import (
    REDACTED,
    collect_secret_values,
    redact_env,
    redact_url_credentials,
)


# --- Redaction helpers ------------------------------------------------------


def test_redact_url_credentials_masks_password():
    pw = "PLACE" + "HOLDER"  # assembled, not a literal secret
    url = f"postgresql://watertwin:{pw}@timescaledb:5432/watertwin"
    redacted = redact_url_credentials(url)
    assert pw not in redacted
    assert f"watertwin:{REDACTED}@timescaledb" in redacted
    # The (non-secret) user and host are preserved for triage.
    assert "postgresql://watertwin:" in redacted
    assert "@timescaledb:5432/watertwin" in redacted


def test_redact_env_masks_secret_named_values():
    token = "TOK" + "VALUE"
    env = {
        "WATERTWIN_SUPPORT_TEST_TOKEN": token,
        "WATERTWIN_OIDC_CLIENT_SECRET": "CS" + "VALUE",
        "WATERTWIN_TENANT_ID": "acme-water",  # not a secret -> preserved
        "UNRELATED_HOST_VAR": "should-be-omitted",
    }
    out = redact_env(env)
    assert out["WATERTWIN_SUPPORT_TEST_TOKEN"] == REDACTED
    assert out["WATERTWIN_OIDC_CLIENT_SECRET"] == REDACTED
    assert out["WATERTWIN_TENANT_ID"] == "acme-water"
    # Only configured prefixes are surfaced at all.
    assert "UNRELATED_HOST_VAR" not in out


def test_public_key_is_not_treated_as_secret():
    env = {"WATERTWIN_OIDC_PUBLIC_KEY": "-----BEGIN PUBLIC KEY-----abc"}
    out = redact_env(env)
    # A *public* key is not a secret; it is preserved (only private keys mask).
    assert out["WATERTWIN_OIDC_PUBLIC_KEY"] != REDACTED


def test_collect_secret_values_finds_names_and_url_passwords():
    token = "TOK" + "SECRET"
    pw = "DBP" + "WORD"
    env = {
        "WATERTWIN_SUPPORT_TEST_TOKEN": token,
        "WATERTWIN_DATABASE_URL": f"postgresql://u:{pw}@h:5432/db",
    }
    secrets = collect_secret_values(env)
    assert token in secrets
    assert pw in secrets


def test_build_bundle_scrubs_secret_from_free_text():
    pw = "LEAK" + "EDPW"
    secret_values = {pw}
    data, _ = support.build_support_bundle(
        entitlements={"tenant_id": "t", "plan": "enterprise"},
        usage={},
        health={"service": "watertwin-api"},
        audit_events=[{"kind": "x", "payload": {"note": f"connect pw={pw}"}}],
        config_env={"WATERTWIN_DATABASE_URL": f"postgresql://u:{pw}@h/db"},
        log_lines=[f"connecting with pw={pw}"],
    )
    text = _all_text(data)
    assert pw not in text
    assert secret_values  # sanity


# --- End-to-end through the admin endpoint ----------------------------------


def _all_text(zip_bytes: bytes) -> str:
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    return "\n".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist())


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_support_bundle_endpoint_contains_no_secrets(client, monkeypatch):
    # Seed secrets (assembled at runtime) into the environment + logs.
    db_pw = "PG" + "Hidden" + "01"
    token = "TOK" + "Hidden" + "02"
    client_secret = "CS" + "Hidden" + "03"
    monkeypatch.setenv(
        "WATERTWIN_DATABASE_URL",
        f"postgresql://watertwin:{db_pw}@timescaledb:5432/watertwin",
    )
    monkeypatch.setenv("WATERTWIN_SUPPORT_TEST_TOKEN", token)
    monkeypatch.setenv("WATERTWIN_OIDC_CLIENT_SECRET", client_secret)

    # A secret that leaked into a log line must be scrubbed too.
    log_buffer.clear()
    import logging

    logging.getLogger("watertwin.support_test").info(
        "startup db=postgresql://watertwin:%s@timescaledb bearer=%s", db_pw, token
    )

    resp = client.post("/api/v1/admin/support/bundle")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    combined = _all_text(resp.content)

    # THE core assertion: no seeded secret appears anywhere in the bundle.
    assert db_pw not in combined
    assert token not in combined
    assert client_secret not in combined

    # The bundle has the expected shape.
    assert "manifest.json" in names
    assert "config-snapshot.json" in names
    assert "logs/watertwin-api.log" in names
    assert any(n.startswith("sbom/") for n in names)

    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["redaction"]["applied"] is True

    # Config snapshot: secret-named values masked; DB URL credentials stripped
    # but the (non-secret) user/host preserved for triage.
    config_snapshot = json.loads(zf.read("config-snapshot.json"))
    assert config_snapshot["WATERTWIN_SUPPORT_TEST_TOKEN"] == REDACTED
    assert config_snapshot["WATERTWIN_OIDC_CLIENT_SECRET"] == REDACTED
    assert REDACTED in config_snapshot["WATERTWIN_DATABASE_URL"]
    assert "postgresql://watertwin:" in config_snapshot["WATERTWIN_DATABASE_URL"]
