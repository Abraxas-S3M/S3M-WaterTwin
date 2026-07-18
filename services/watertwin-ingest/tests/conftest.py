"""Test bootstrap: make shared packages + the service importable."""
"""Test bootstrap: make the service importable regardless of the CWD."""
"""Test bootstrap: make shared packages + the ingest service importable."""

from __future__ import annotations

import os
import sys

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)
"""Test bootstrap: make shared packages + the service app importable, isolate state."""

from __future__ import annotations

"""Shared fixtures for the watertwin-ingest test suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from ot_ingestion.tag_normalization import TagMap

from app.staging import StagingStore


@pytest.fixture()
def tag_map() -> TagMap:
    """A small, explicit customer tag map (no guessing)."""
    return TagMap.from_dict(
        {
            "map_id": "test-plant",
            "tags": {
                "HIST.PT-101.PV": {
                    "asset_id": "AST-HPP-01",
                    "metric": "discharge_pressure_bar",
                    "unit": "bar",
                },
                "HIST.FT-201.PV": {
                    "asset_id": "AST-RO-01",
                    "metric": "feed_flow_m3h",
                    "unit": "m3/h",
                    "scale": 1.0,
                    "offset": 0.0,
                },
            },
        }
    )


@pytest.fixture()
def staging(tmp_path: Path) -> StagingStore:
    return StagingStore(tmp_path / "staging")
"""Test bootstrap: make shared packages + service importable and isolate state.

The suite runs the ingest service under ENFORCED Keycloak-style auth, validating
RS256 JWTs against a locally-generated RSA key (supplied via
``WATERTWIN_OIDC_PUBLIC_KEY`` instead of a live JWKS endpoint) -- the same
pattern watertwin-api uses. The content store is pointed at a throwaway temp
directory and the audit client uses the in-process transport so tests can
inspect the hash-chained entries.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(SERVICE_ROOT))
PACKAGES = os.path.join(REPO_ROOT, "packages")

for path in (PACKAGES, SERVICE_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

# Isolate the sandbox scratch directory before the app imports config.
_tmp = tempfile.mkdtemp(prefix="watertwin-ingest-test-")
os.environ.setdefault("WATERTWIN_INGEST_SCRATCH_DIR", os.path.join(_tmp, "scratch"))

#: Path to the bundled RO/pumping-station demo network (shared with the twin).
DEMO_INP = os.path.join(PACKAGES, "network_twin", "networks", "ro-handoff.inp")
# Isolate the write-once content store to a throwaway directory before
# app.config is imported.
_tmp = tempfile.mkdtemp(prefix="watertwin-ingest-test-")
os.environ.setdefault("INGEST_STORAGE_ROOT", os.path.join(_tmp, "store"))
# Enforced auth by default; no API token so the audit client uses the in-memory
# transport the tests inspect.
os.environ.pop("WATERTWIN_AUTH_DISABLED", None)
os.environ.pop("INGEST_API_TOKEN", None)
os.environ.setdefault("DEPLOYMENT_PROFILE", "standard")

import jwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

TEST_ISSUER = "https://keycloak.test/realms/watertwin"


@pytest.fixture(scope="session")
def rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def make_token(private_pem: str, *, username: str, roles: list[str], tenant_id: str) -> str:
    now = dt.datetime.now(tz=dt.timezone.utc)
    claims = {
        "sub": f"user-{username}",
        "preferred_username": username,
        "email": f"{username}@watertwin.local",
        "iss": TEST_ISSUER,
        "iat": now,
        "exp": now + dt.timedelta(minutes=15),
        "realm_access": {"roles": roles},
        "tenant_id": tenant_id,
    }
    return jwt.encode(claims, private_pem, algorithm="RS256")


@pytest.fixture()
def client(monkeypatch, rsa_keypair):
    """Enforced-auth TestClient with tokens verified against the local RSA key."""
    private_pem, public_pem = rsa_keypair
    monkeypatch.setenv("WATERTWIN_AUTH_DISABLED", "false")
    monkeypatch.setenv("WATERTWIN_OIDC_PUBLIC_KEY", public_pem)
    monkeypatch.setenv("WATERTWIN_OIDC_ISSUER", TEST_ISSUER)
    monkeypatch.delenv("WATERTWIN_OIDC_AUDIENCE", raising=False)
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "standard")

    from app import events
    from app.audit_client import AuditClient, InMemoryAuditTransport
    from app.main import app, reset_state, set_antivirus, set_audit_client
    from app.scanner import NoOpAntivirus

    reset_state()
    events.reset_bus()
    set_audit_client(AuditClient(InMemoryAuditTransport()))
    set_antivirus(NoOpAntivirus())

    def token(username: str, roles: list[str], tenant_id: str = "TEN-A") -> dict:
        return {
            "Authorization": (
                f"Bearer {make_token(private_pem, username=username, roles=roles, tenant_id=tenant_id)}"
            )
        }

    with TestClient(app) as c:
        c.token = token  # type: ignore[attr-defined]
        yield c
    events.reset_bus()
"""Shared pytest fixtures for the watertwin-ingest suites."""

from __future__ import annotations

import os

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def fixtures_dir() -> str:
    """Absolute path to the committed test fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def read_fixture():
    """Return a helper that reads a fixture file's raw bytes."""

    def _read(name: str) -> bytes:
        with open(os.path.join(FIXTURES_DIR, name), "rb") as fh:
            return fh.read()

    return _read
