"""Auth-enabled RBAC tests for watertwin-api.

These flip the service into its *enforced* authentication mode
(``WATERTWIN_AUTH_DISABLED=false``) and validate real Keycloak-style JWT bearer
tokens against a locally generated RSA key (supplied via
``WATERTWIN_OIDC_PUBLIC_KEY`` instead of a live JWKS endpoint). They lock the
RBAC matrix and prove that the authenticated identity flows into the audit
trail.

The rest of the suites run under the dev-mode bypass (see ``conftest.py``); this
module is the dedicated enforced-auth coverage the work package calls for.
"""

from __future__ import annotations

import datetime as dt

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from simulation_contracts import (
    ScenarioDelta,
    ScenarioType,
    SimulationOutputs,
    SimulationResult,
)

TEST_ISSUER = "https://keycloak.test/realms/watertwin"


class FakeHydraulicClient:
    """Deterministic in-process stand-in (no EPANET) so a run can be seeded."""

    def health(self) -> dict:
        return {"status": "healthy", "service": "hydraulic-sim"}

    def network_info(self) -> dict:
        return {"train_id": "RO-TRAIN-001", "pumps": ["PU-PROD-1", "PU-PROD-2"]}

    def run(
        self,
        scenario: ScenarioType,
        parameters=None,
        facility_id: str = "S3M-DESAL-01",
        train_id: str = "RO-TRAIN-001",
        requested_by=None,
    ) -> SimulationResult:
        if scenario == ScenarioType.baseline:
            return SimulationResult(
                job_id="sim-baseline01",
                scenario=ScenarioType.baseline,
                outputs=SimulationOutputs(delivered_flow_m3h=100.0),
                confidence=0.8,
                assumptions=["steady-state demand"],
            )
        delta = ScenarioDelta(
            delivered_flow_baseline_m3h=100.0,
            delivered_flow_scenario_m3h=70.0,
            delivered_flow_delta_m3h=-30.0,
            delivered_flow_delta_pct=-30.0,
            min_pressure_baseline_m=30.0,
            min_pressure_scenario_m=22.0,
        )
        return SimulationResult(
            job_id="sim-scenario01",
            scenario=scenario,
            outputs=SimulationOutputs(delivered_flow_m3h=70.0, delta_vs_baseline=delta),
            confidence=0.7,
            assumptions=["steady-state demand", "single duty pump offline"],
        )


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


def _make_token(private_pem: str, *, username: str, roles: list[str]) -> str:
    now = dt.datetime.now(tz=dt.timezone.utc)
    claims = {
        "sub": f"user-{username}",
        "preferred_username": username,
        "email": f"{username}@watertwin.local",
        "iss": TEST_ISSUER,
        "iat": now,
        "exp": now + dt.timedelta(minutes=15),
        "realm_access": {"roles": roles},
    }
    return jwt.encode(claims, private_pem, algorithm="RS256")


@pytest.fixture()
def auth_client(monkeypatch, rsa_keypair):
    """Enforced-auth TestClient with tokens verified against the local RSA key."""
    private_pem, public_pem = rsa_keypair
    monkeypatch.setenv("WATERTWIN_AUTH_DISABLED", "false")
    monkeypatch.setenv("WATERTWIN_OIDC_PUBLIC_KEY", public_pem)
    monkeypatch.setenv("WATERTWIN_OIDC_ISSUER", TEST_ISSUER)
    monkeypatch.delenv("WATERTWIN_OIDC_AUDIENCE", raising=False)

    from app.main import app, reco_store, store

    app.state.hydraulic_client = FakeHydraulicClient()
    # Clear shared state directly (reset is itself an RBAC-gated endpoint).
    reco_store.clear()
    store.reset()

    def token(username: str, roles: list[str]) -> dict:
        return {"Authorization": f"Bearer {_make_token(private_pem, username=username, roles=roles)}"}

    with TestClient(app) as c:
        c.token = token  # type: ignore[attr-defined]
        yield c


def _seed_recommendation(auth_client) -> str:
    """Run a scenario as an engineer to create a pending recommendation."""
    resp = auth_client.post(
        "/api/v1/simulation-center/run",
        headers=auth_client.token("erin-engineer", ["engineer"]),
        json={"scenario": "pump_outage", "parameters": {"pump_id": "PU-PROD-2"}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["recommendation"]["recommendation_id"]


# --- Authentication ---------------------------------------------------------


def test_health_is_open_without_auth(auth_client):
    # Liveness must not require a token (used by container health checks).
    assert auth_client.get("/health").status_code == 200


def test_unauthenticated_request_to_protected_endpoint_is_401(auth_client):
    resp = auth_client.get("/api/v1/water-quality/status")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_invalid_token_is_401(auth_client):
    resp = auth_client.get(
        "/api/v1/water-quality/status",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert resp.status_code == 401


def test_any_authenticated_role_may_read(auth_client):
    resp = auth_client.get(
        "/api/v1/water-quality/status",
        headers=auth_client.token("val-viewer", ["viewer"]),
    )
    assert resp.status_code == 200


# --- RBAC matrix ------------------------------------------------------------


def test_viewer_cannot_approve_recommendation_403(auth_client):
    rec_id = _seed_recommendation(auth_client)
    resp = auth_client.post(
        f"/api/v1/recommendations/{rec_id}/decision",
        headers=auth_client.token("val-viewer", ["viewer"]),
        json={"status": "approved"},
    )
    assert resp.status_code == 403


def test_operator_can_approve_and_identity_is_audited(auth_client):
    rec_id = _seed_recommendation(auth_client)
    resp = auth_client.post(
        f"/api/v1/recommendations/{rec_id}/decision",
        headers=auth_client.token("ola-operator", ["operator"]),
        json={"status": "approved", "actor": "spoofed-should-be-ignored"},
    )
    assert resp.status_code == 200
    assert resp.json()["approval_status"] == "approved"

    # The audit event records the authenticated operator, not the request body.
    events = auth_client.get(
        "/api/v1/audit", headers=auth_client.token("ada-admin", ["admin"])
    ).json()["events"]
    decision = next(e for e in events if e["kind"] == "recommendation.decision")
    assert decision["actor"] == "ola-operator"


def test_viewer_cannot_run_scenario_403(auth_client):
    resp = auth_client.post(
        "/api/v1/simulation-center/run",
        headers=auth_client.token("val-viewer", ["viewer"]),
        json={"scenario": "pump_outage", "parameters": {"pump_id": "PU-PROD-2"}},
    )
    assert resp.status_code == 403


def test_engineer_can_run_scenario_and_is_audited(auth_client):
    _seed_recommendation(auth_client)
    events = auth_client.get(
        "/api/v1/audit", headers=auth_client.token("ada-admin", ["admin"])
    ).json()["events"]
    run = next(e for e in events if e["kind"] == "scenario.run")
    assert run["actor"] == "erin-engineer"


def test_viewer_cannot_reset_403_but_engineer_can(auth_client):
    assert (
        auth_client.post(
            "/api/v1/reset", headers=auth_client.token("val-viewer", ["viewer"])
        ).status_code
        == 403
    )
    assert (
        auth_client.post(
            "/api/v1/reset", headers=auth_client.token("erin-engineer", ["engineer"])
        ).status_code
        == 200
    )


def test_viewer_cannot_read_audit_403(auth_client):
    resp = auth_client.get(
        "/api/v1/audit", headers=auth_client.token("val-viewer", ["viewer"])
    )
    assert resp.status_code == 403


def test_auditor_can_read_audit(auth_client):
    resp = auth_client.get(
        "/api/v1/audit", headers=auth_client.token("aud-auditor", ["auditor"])
    )
    assert resp.status_code == 200
    assert "events" in resp.json()


def test_admin_is_superset_of_all_roles(auth_client):
    admin = auth_client.token("ada-admin", ["admin"])
    rec_id = _seed_recommendation(auth_client)
    assert auth_client.get("/api/v1/audit", headers=admin).status_code == 200
    assert (
        auth_client.post(
            f"/api/v1/recommendations/{rec_id}/decision",
            headers=admin,
            json={"status": "rejected"},
        ).status_code
        == 200
    )
    assert auth_client.post("/api/v1/reset", headers=admin).status_code == 200


def test_boundary_still_read_only_under_auth(auth_client):
    # The advisory/read-only posture is unchanged by authentication.
    body = auth_client.get("/health").json()
    assert body["control_write_enabled"] is False
    assert body["operator_approval_required"] is True
