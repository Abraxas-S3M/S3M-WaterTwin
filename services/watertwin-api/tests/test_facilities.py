"""Tenant/facility scoping tests for the multi-facility administration surface.

These lock the guarantee that a signed-in identity only ever sees facilities it
is entitled to, and that fleet roll-up totals never include cross-tenant data.

Two layers are covered:
  * the pure scoping module (``app.facilities``) against constructed principals;
  * the HTTP endpoints under both the dev bypass and enforced Keycloak auth.
"""

from __future__ import annotations

import datetime as dt

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import facilities as facilities_mod
from app.auth import Principal

TEST_ISSUER = "https://keycloak.test/realms/watertwin"


# --- Pure module scoping ----------------------------------------------------


def _principal(roles, *, tenant_id, facility_ids=()):
    return Principal(
        username="p",
        roles=frozenset(roles),
        tenant_id=tenant_id,
        facility_ids=frozenset(facility_ids),
    )


def test_tenant_admin_sees_all_facilities_in_tenant():
    admin = _principal(["tenant-admin"], tenant_id="TEN-ACME")
    resp = facilities_mod.list_facilities(admin)
    ids = {f["facility_id"] for f in resp["facilities"]}
    assert ids == {"FAC-ALPHA", "FAC-BETA", "FAC-GAMMA"}
    # Never leaks the foreign tenant's facility.
    assert "FAC-OMEGA" not in ids
    assert all(f["tenant_id"] == "TEN-ACME" for f in resp["facilities"])


def test_facility_operator_is_scoped_to_assigned_facility():
    op = _principal(
        ["facility-operator"], tenant_id="TEN-ACME", facility_ids=["FAC-ALPHA"]
    )
    resp = facilities_mod.list_facilities(op)
    assert [f["facility_id"] for f in resp["facilities"]] == ["FAC-ALPHA"]


def test_foreign_tenant_admin_never_sees_other_tenant():
    globex = _principal(["tenant-admin"], tenant_id="TEN-GLOBEX")
    resp = facilities_mod.list_facilities(globex)
    ids = {f["facility_id"] for f in resp["facilities"]}
    assert ids == {"FAC-OMEGA"}
    assert all(f["tenant_id"] == "TEN-GLOBEX" for f in resp["facilities"])


def test_no_tenant_sees_nothing():
    nobody = _principal(["viewer"], tenant_id=None)
    assert facilities_mod.list_facilities(nobody)["facilities"] == []


def test_non_manager_without_assignments_sees_nothing():
    viewer = _principal(["viewer"], tenant_id="TEN-ACME")
    assert facilities_mod.list_facilities(viewer)["facilities"] == []


def test_fleet_overview_totals_are_tenant_scoped():
    admin = _principal(["tenant-admin"], tenant_id="TEN-ACME")
    fleet = facilities_mod.fleet_overview(admin)
    totals = fleet["totals"]
    assert totals["facility_count"] == 3
    assert totals["online_count"] == 2
    assert totals["total_power_kw"] == pytest.approx(1520 + 980 + 1750)
    assert totals["total_active_alarms"] == 4
    assert totals["total_production_m3_day"] == pytest.approx(11952 + 8000 + 14000)
    assert totals["worst_band"] == "Degraded"
    # Foreign facility's metrics must not appear.
    assert all(r["tenant_id"] == "TEN-ACME" for r in fleet["facilities"])


def test_fleet_overview_scoped_for_facility_operator():
    op = _principal(
        ["facility-operator"], tenant_id="TEN-ACME", facility_ids=["FAC-ALPHA"]
    )
    fleet = facilities_mod.fleet_overview(op)
    assert [r["facility_id"] for r in fleet["facilities"]] == ["FAC-ALPHA"]
    assert fleet["totals"]["facility_count"] == 1
    assert fleet["totals"]["total_power_kw"] == pytest.approx(1520)


# --- HTTP: dev bypass -------------------------------------------------------


def test_endpoints_under_dev_bypass_scope_to_dev_tenant():
    # conftest sets WATERTWIN_AUTH_DISABLED=true -> synthetic admin on TEN-ACME.
    from app.main import app

    with TestClient(app) as c:
        resp = c.get("/api/v1/facilities")
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == "TEN-ACME"
        ids = {f["facility_id"] for f in body["facilities"]}
        assert ids == {"FAC-ALPHA", "FAC-BETA", "FAC-GAMMA"}
        assert "FAC-OMEGA" not in ids

        fleet = c.get("/api/v1/fleet/overview").json()
        assert fleet["totals"]["facility_count"] == 3
        assert all(r["tenant_id"] == "TEN-ACME" for r in fleet["facilities"])


# --- HTTP: enforced Keycloak auth -------------------------------------------


@pytest.fixture(scope="module")
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


def _make_token(private_pem, *, username, roles, tenant_id=None, facility_ids=None):
    now = dt.datetime.now(tz=dt.timezone.utc)
    claims = {
        "sub": f"user-{username}",
        "preferred_username": username,
        "iss": TEST_ISSUER,
        "iat": now,
        "exp": now + dt.timedelta(minutes=15),
        "realm_access": {"roles": roles},
    }
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    if facility_ids is not None:
        claims["facility_ids"] = facility_ids
    return jwt.encode(claims, private_pem, algorithm="RS256")


@pytest.fixture()
def auth_client(monkeypatch, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    monkeypatch.setenv("WATERTWIN_AUTH_DISABLED", "false")
    monkeypatch.setenv("WATERTWIN_OIDC_PUBLIC_KEY", public_pem)
    monkeypatch.setenv("WATERTWIN_OIDC_ISSUER", TEST_ISSUER)
    monkeypatch.delenv("WATERTWIN_OIDC_AUDIENCE", raising=False)

    from app.main import app

    def token(username, roles, **scope):
        return {
            "Authorization": f"Bearer {_make_token(private_pem, username=username, roles=roles, **scope)}"
        }

    with TestClient(app) as c:
        c.token = token  # type: ignore[attr-defined]
        yield c


def test_unauthenticated_facilities_is_401(auth_client):
    assert auth_client.get("/api/v1/facilities").status_code == 401


def test_tenant_admin_token_scopes_to_its_tenant(auth_client):
    resp = auth_client.get(
        "/api/v1/facilities",
        headers=auth_client.token("tara-admin", ["tenant-admin"], tenant_id="TEN-ACME"),
    )
    assert resp.status_code == 200
    ids = {f["facility_id"] for f in resp.json()["facilities"]}
    assert ids == {"FAC-ALPHA", "FAC-BETA", "FAC-GAMMA"}


def test_facility_operator_token_scopes_to_one_facility(auth_client):
    resp = auth_client.get(
        "/api/v1/facilities",
        headers=auth_client.token(
            "ola-operator",
            ["facility-operator"],
            tenant_id="TEN-ACME",
            facility_ids=["FAC-ALPHA"],
        ),
    )
    assert resp.status_code == 200
    assert [f["facility_id"] for f in resp.json()["facilities"]] == ["FAC-ALPHA"]


def test_foreign_tenant_token_cannot_see_acme(auth_client):
    resp = auth_client.get(
        "/api/v1/fleet/overview",
        headers=auth_client.token(
            "gwen-globex", ["tenant-admin"], tenant_id="TEN-GLOBEX"
        ),
    )
    assert resp.status_code == 200
    rows = resp.json()["facilities"]
    assert [r["facility_id"] for r in rows] == ["FAC-OMEGA"]
    assert all(r["tenant_id"] == "TEN-GLOBEX" for r in rows)
