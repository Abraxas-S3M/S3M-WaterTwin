"""Tenant + facility scoping: row-level isolation, API denial, migration parity.

These lock the multi-tenant scoping work package:

* **Store row-level scoping** — audit + recommendation reads are filtered by
  tenant/facility, and the pre-multi-tenancy (single-facility) data migrates into
  the default tenant/facility with full parity and an *unchanged* audit chain.
* **API cross-tenant denial** — a principal may only read within the
  tenant/facility carried in its token; cross-tenant reads are denied (403).
* **Facility filter applied to analytics + config + audit** — the three read
  surfaces the platform exposes are all row-level scoped.

The API tests flip the service into its enforced Keycloak-validation mode and
mint tenant/facility-scoped JWTs (verified against a local RSA key), mirroring
``tests/test_auth.py``.
"""

from __future__ import annotations

import datetime as dt

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import config
from app.store import Store
from simulation_contracts import (
    ScenarioDelta,
    ScenarioType,
    SimulationOutputs,
    SimulationResult,
)

TEST_ISSUER = "https://keycloak.test/realms/watertwin"


# ===========================================================================
# Store-level: row-level scoping + migration parity (in-memory, no database)
# ===========================================================================


@pytest.fixture()
def store() -> Store:
    return Store(database_url=None, connect=False)


def test_audit_events_are_tagged_with_default_scope(store: Store):
    ev = store.audit("scenario.run", payload={"i": 1})
    assert ev["tenant_id"] == config.DEFAULT_TENANT_ID
    assert ev["facility_id"] == config.DEFAULT_FACILITY_ID


def test_recent_audit_is_row_level_scoped_by_tenant_and_facility(store: Store):
    store.audit("a", tenant_id="tenant-a", facility_id="FAC-A")
    store.audit("b", tenant_id="tenant-b", facility_id="FAC-B")
    store.audit("c", tenant_id="tenant-a", facility_id="FAC-A2")

    only_a = store.recent_audit(tenant_id="tenant-a")
    assert {e["kind"] for e in only_a} == {"a", "c"}

    only_a_faca = store.recent_audit(tenant_id="tenant-a", facility_id="FAC-A")
    assert {e["kind"] for e in only_a_faca} == {"a"}

    only_b = store.recent_audit(tenant_id="tenant-b")
    assert {e["kind"] for e in only_b} == {"b"}

    # Unscoped read (global/admin + internal verification) sees everything.
    assert {e["kind"] for e in store.recent_audit()} == {"a", "b", "c"}


def test_facility_agnostic_events_stay_visible_within_tenant(store: Store):
    # A tenant-scoped, facility-agnostic event (no facility_id at all, as a legacy
    # or system row would appear): it must remain visible within its tenant even
    # when a facility filter is applied.
    store.audit("system.reset", tenant_id="tenant-a")
    store._audit_mem[-1]["facility_id"] = None
    store.audit("scenario.run", tenant_id="tenant-a", facility_id="FAC-A")

    events = store.recent_audit(tenant_id="tenant-a", facility_id="FAC-A")
    # Both the facility-agnostic and the FAC-A events show.
    assert {e["kind"] for e in events} == {"system.reset", "scenario.run"}


def test_recommendations_are_row_level_scoped(store: Store):
    store.save_recommendation("rec-a", {"x": 1}, tenant_id="tenant-a", facility_id="FAC-A")
    store.save_recommendation("rec-b", {"x": 2}, tenant_id="tenant-b", facility_id="FAC-B")

    a = store.list_recommendations(tenant_id="tenant-a")
    assert {r["recommendation_id"] for r in a} == {"rec-a"}
    b = store.list_recommendations(tenant_id="tenant-b", facility_id="FAC-B")
    assert {r["recommendation_id"] for r in b} == {"rec-b"}
    assert len(store.list_recommendations()) == 2


def test_migration_parity_backfills_legacy_data_without_changing_the_chain(store: Store):
    # Seed data the way the pre-multi-tenancy platform did, then strip the scope
    # columns to emulate legacy rows created before tenant/facility existed.
    for i in range(3):
        store.audit("scenario.run", payload={"i": i})
    store.save_recommendation("rec-legacy-1", {"x": 1})
    store.save_recommendation("rec-legacy-2", {"x": 2})

    for ev in store._audit_mem:
        ev.pop("tenant_id", None)
        ev.pop("facility_id", None)
    for rec in store._rec_mem.values():
        rec.pop("tenant_id", None)
        rec.pop("facility_id", None)

    audit_before = len(store.audit_chain_asc())
    rec_before = len(store.list_recommendations())
    # The tamper-evident chain is intact before migration...
    assert store.verify_chain()["ok"] is True

    migrated = store.migrate_default_scope()

    # Parity: every legacy record is accounted for, none lost or duplicated.
    assert migrated == {"audit": 3, "recommendations": 2}
    assert len(store.audit_chain_asc()) == audit_before
    assert len(store.list_recommendations()) == rec_before

    # ...and the invariant is unchanged: backfilling the (non-hashed) scope
    # columns leaves the hash chain valid.
    assert store.verify_chain()["ok"] is True

    # Everything now lives in the default tenant/facility and is visible there.
    default_events = store.recent_audit(
        tenant_id=config.DEFAULT_TENANT_ID, facility_id=config.DEFAULT_FACILITY_ID
    )
    assert len(default_events) == 3
    assert not store.recent_audit(tenant_id="some-other-tenant")
    for rec in store.list_recommendations(tenant_id=config.DEFAULT_TENANT_ID):
        assert rec["tenant_id"] == config.DEFAULT_TENANT_ID
        assert rec["facility_id"] == config.DEFAULT_FACILITY_ID


def test_migration_is_idempotent(store: Store):
    store.audit("scenario.run")
    store.save_recommendation("rec-1", {"x": 1})
    # Already scoped -> re-running the migration touches nothing.
    assert store.migrate_default_scope() == {"audit": 0, "recommendations": 0}


# ===========================================================================
# API-level: cross-tenant denial + facility filter on analytics/config/audit
# ===========================================================================


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


def _make_token(
    private_pem: str,
    *,
    username: str,
    roles: list[str],
    tenants: list[str] | None = None,
    facilities: list[str] | None = None,
) -> str:
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
    if tenants is not None:
        claims["tenant_ids"] = tenants
    if facilities is not None:
        claims["facility_ids"] = facilities
    return jwt.encode(claims, private_pem, algorithm="RS256")


@pytest.fixture()
def auth_client(monkeypatch, rsa_keypair):
    """Enforced-auth TestClient with tenant/facility-scoped tokens."""
    private_pem, public_pem = rsa_keypair
    monkeypatch.setenv("WATERTWIN_AUTH_DISABLED", "false")
    monkeypatch.setenv("WATERTWIN_OIDC_PUBLIC_KEY", public_pem)
    monkeypatch.setenv("WATERTWIN_OIDC_ISSUER", TEST_ISSUER)
    monkeypatch.delenv("WATERTWIN_OIDC_AUDIENCE", raising=False)

    from app.main import app, reco_store, store

    app.state.hydraulic_client = FakeHydraulicClient()
    reco_store.clear()
    store.reset()

    def token(username, roles, tenants=None, facilities=None) -> dict:
        return {
            "Authorization": "Bearer "
            + _make_token(
                private_pem,
                username=username,
                roles=roles,
                tenants=tenants,
                facilities=facilities,
            )
        }

    with TestClient(app) as c:
        c.token = token  # type: ignore[attr-defined]
        yield c


# --- cross-tenant read denial ----------------------------------------------


def test_cross_tenant_analytics_read_is_denied(auth_client):
    headers = auth_client.token(
        "ava", ["viewer"], tenants=["tenant-a"], facilities=["FAC-A"]
    )
    # Reading another tenant's facility is denied.
    denied = auth_client.get(
        "/api/v1/water-quality/status?tenant_id=tenant-b&facility_id=FAC-B",
        headers=headers,
    )
    assert denied.status_code == 403

    # Reading the caller's own tenant/facility is allowed and scoped.
    ok = auth_client.get(
        "/api/v1/water-quality/status?tenant_id=tenant-a&facility_id=FAC-A",
        headers=headers,
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["tenant_id"] == "tenant-a"
    assert body["facility_id"] == "FAC-A"


def test_cross_facility_read_within_tenant_is_denied(auth_client):
    # Member of tenant-a but only facility FAC-A.
    headers = auth_client.token(
        "ava", ["engineer"], tenants=["tenant-a"], facilities=["FAC-A"]
    )
    denied = auth_client.get(
        "/api/v1/energy/summary?tenant_id=tenant-a&facility_id=FAC-B", headers=headers
    )
    assert denied.status_code == 403


# --- facility filter applied to analytics ----------------------------------


def test_analytics_envelope_reflects_requested_facility(auth_client):
    headers = auth_client.token(
        "ava", ["viewer"], tenants=["tenant-a"], facilities=["FAC-A", "FAC-B"]
    )
    for facility in ("FAC-A", "FAC-B"):
        body = auth_client.get(
            f"/api/v1/maintenance/ranking?tenant_id=tenant-a&facility_id={facility}",
            headers=headers,
        ).json()
        assert body["tenant_id"] == "tenant-a"
        assert body["facility_id"] == facility


# --- facility filter applied to config (recommendations) -------------------


def _run_scenario(auth_client, *, username, tenant, facility) -> str:
    resp = auth_client.post(
        "/api/v1/simulation-center/run",
        headers=auth_client.token(
            username, ["engineer"], tenants=[tenant], facilities=[facility]
        ),
        json={
            "scenario": "pump_outage",
            "parameters": {"pump_id": "PU-PROD-2"},
            "tenant_id": tenant,
            "facility_id": facility,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["recommendation"]["recommendation_id"]


def test_recommendation_config_list_is_facility_scoped(auth_client):
    rec_a = _run_scenario(auth_client, username="erin", tenant="tenant-a", facility="FAC-A")
    rec_b = _run_scenario(auth_client, username="bob", tenant="tenant-b", facility="FAC-B")
    assert rec_a != rec_b

    a_headers = auth_client.token(
        "ava", ["viewer"], tenants=["tenant-a"], facilities=["FAC-A"]
    )
    a_recs = auth_client.get("/api/v1/recommendations", headers=a_headers).json()
    a_ids = {r["recommendation_id"] for r in a_recs}
    assert rec_a in a_ids
    assert rec_b not in a_ids
    for r in a_recs:
        assert r["tenant_id"] == "tenant-a"
        assert r["facility_id"] == "FAC-A"

    # tenant-a cannot fetch tenant-b's record by id (reported as not-found).
    assert (
        auth_client.get(f"/api/v1/recommendations/{rec_b}", headers=a_headers).status_code
        == 404
    )
    # ...but tenant-b can.
    b_headers = auth_client.token(
        "ben", ["viewer"], tenants=["tenant-b"], facilities=["FAC-B"]
    )
    assert (
        auth_client.get(f"/api/v1/recommendations/{rec_b}", headers=b_headers).status_code
        == 200
    )


# --- facility filter applied to audit --------------------------------------


def test_audit_trail_is_tenant_scoped(auth_client):
    _run_scenario(auth_client, username="erin", tenant="tenant-a", facility="FAC-A")
    _run_scenario(auth_client, username="bob", tenant="tenant-b", facility="FAC-B")

    a_events = auth_client.get(
        "/api/v1/audit",
        headers=auth_client.token("aud", ["auditor"], tenants=["tenant-a"]),
    ).json()["events"]
    assert a_events, "tenant-a auditor should see its own events"
    assert all(e["tenant_id"] == "tenant-a" for e in a_events)
    assert any(e["kind"] == "scenario.run" for e in a_events)

    b_events = auth_client.get(
        "/api/v1/audit",
        headers=auth_client.token("aud", ["auditor"], tenants=["tenant-b"]),
    ).json()["events"]
    assert b_events
    assert all(e["tenant_id"] == "tenant-b" for e in b_events)


def test_auditor_cannot_read_another_tenants_audit_via_query(auth_client):
    resp = auth_client.get(
        "/api/v1/audit?tenant_id=tenant-b",
        headers=auth_client.token("aud", ["auditor"], tenants=["tenant-a"]),
    )
    assert resp.status_code == 403


def test_audit_can_be_filtered_to_a_facility(auth_client):
    _run_scenario(auth_client, username="erin", tenant="tenant-a", facility="FAC-A")
    _run_scenario(auth_client, username="erin2", tenant="tenant-a", facility="FAC-A2")

    events = auth_client.get(
        "/api/v1/audit?tenant_id=tenant-a&facility_id=FAC-A",
        headers=auth_client.token(
            "aud", ["auditor"], tenants=["tenant-a"], facilities=["FAC-A", "FAC-A2"]
        ),
    ).json()["events"]
    assert events
    for e in events:
        # Facility-agnostic events (facility_id None) stay visible within tenant.
        assert e["facility_id"] in (None, "FAC-A")


# --- invariant unchanged ----------------------------------------------------


def test_read_only_control_boundary_invariant_unchanged(auth_client):
    body = auth_client.get("/health").json()
    assert body["control_write_enabled"] is False
    assert body["operator_approval_required"] is True

    # The tamper-evident audit chain still verifies under tenant scoping.
    _run_scenario(auth_client, username="erin", tenant="tenant-a", facility="FAC-A")
    verify = auth_client.get(
        "/api/v1/audit/verify",
        headers=auth_client.token("aud", ["auditor"], tenants=["tenant-a"]),
    )
    assert verify.status_code == 200
    assert verify.json()["ok"] is True
