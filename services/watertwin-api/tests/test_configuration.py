"""Tests for the versioned, approval-gated configuration service.

Covers the version lifecycle (draft -> submitted -> approved -> active,
immutable-on-publish, supersede-only), the tamper-evident audit entry emitted on
every state change, RBAC-gated approval (viewer/operator denied), the
tag-mapping round-trip through ``app.tag_normalization``, and the pump-curve /
membrane-model validation ranges.

The service-level tests run against a pure in-memory :class:`Store`
(``connect=False``). The RBAC tests flip the service into enforced Keycloak-JWT
mode (mirroring ``tests/test_auth.py``) to prove only engineer/admin may approve.
"""

from __future__ import annotations

import datetime as dt

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.configuration.service import (
    ConfigConflictError,
    ConfigService,
    ConfigValidationError,
)
from app.store import Store
from app.tag_normalization import RawReading, normalize


@pytest.fixture()
def service() -> ConfigService:
    return ConfigService(Store(database_url=None, connect=False))


def _asset_payload(asset_id: str = "AST-HPP-01") -> dict:
    return {
        "asset_id": asset_id,
        "name": "High-pressure pump 01",
        "asset_type": "hp_pump",
        "facility_id": "S3M-DESAL-01",
        "train_id": "RO-TRAIN-001",
        "criticality": "critical",
    }


def _pump_curve_payload() -> dict:
    return {
        "asset_id": "AST-HPP-01",
        "name": "duty-curve",
        "speed_rpm": 1480,
        "points": [
            {"flow_m3h": 0.0, "head_m": 320.0, "efficiency": 0.60},
            {"flow_m3h": 120.0, "head_m": 300.0, "efficiency": 0.82},
            {"flow_m3h": 240.0, "head_m": 250.0, "efficiency": 0.80},
        ],
    }


def _membrane_payload() -> dict:
    return {
        "model_name": "SW30HRLE-440",
        "manufacturer": "ACME",
        "element_type": "seawater-ro",
        "active_area_m2": 41.0,
        "nominal_salt_rejection_pct": 99.8,
        "max_feed_pressure_bar": 83.0,
        "max_feed_flow_m3h": 17.0,
        "min_concentrate_flow_m3h": 3.6,
        "max_recovery": 0.15,
    }


# --- version lifecycle ------------------------------------------------------


def test_version_lifecycle_draft_submitted_active(service: ConfigService):
    created = service.create("asset", _asset_payload(), actor="erin-engineer")
    assert created.status.value == "draft"
    assert created.version == 1
    assert created.config_id == "AST-HPP-01"

    submitted = service.publish("asset", "AST-HPP-01", actor="erin-engineer")
    assert submitted.status.value == "submitted"
    assert submitted.submitted_by == "erin-engineer"

    active = service.approve("asset", "AST-HPP-01", actor="ada-admin")
    assert active.status.value == "active"
    assert active.approved_by == "ada-admin"
    assert active.activated_at is not None


def test_payload_is_immutable_once_published(service: ConfigService):
    service.create("asset", _asset_payload(), actor="eng")
    service.publish("asset", "AST-HPP-01", actor="eng")
    # A submitted version is frozen: editing it is a conflict.
    with pytest.raises(ConfigConflictError):
        service.update("asset", "AST-HPP-01", _asset_payload(), actor="eng")


def test_draft_is_editable_before_publish(service: ConfigService):
    service.create("asset", _asset_payload(), actor="eng")
    payload = _asset_payload()
    payload["name"] = "Renamed pump"
    updated = service.update("asset", "AST-HPP-01", payload, actor="eng")
    assert updated.payload["name"] == "Renamed pump"
    assert updated.status.value == "draft"


def test_approve_requires_submitted(service: ConfigService):
    service.create("asset", _asset_payload(), actor="eng")
    # Cannot approve a draft that was never submitted.
    with pytest.raises(ConfigConflictError):
        service.approve("asset", "AST-HPP-01", actor="eng")


def test_new_version_supersedes_prior_active_no_delete(service: ConfigService):
    service.create("asset", _asset_payload(), actor="eng")
    service.publish("asset", "AST-HPP-01", actor="eng")
    v1 = service.approve("asset", "AST-HPP-01", actor="eng")
    assert v1.version == 1 and v1.status.value == "active"

    # A second version supersedes the first once approved.
    updated = _asset_payload()
    updated["criticality"] = "high"
    service.create("asset", updated, actor="eng", config_id="AST-HPP-01")
    service.publish("asset", "AST-HPP-01", actor="eng")
    v2 = service.approve("asset", "AST-HPP-01", actor="eng")
    assert v2.version == 2 and v2.status.value == "active"

    versions = {v.version: v for v in service.list_versions("asset", "AST-HPP-01")}
    # v1 is superseded (not deleted) and points at v2.
    assert versions[1].status.value == "superseded"
    assert versions[1].superseded_by == v2.version_id
    # There is exactly one active version.
    active = service.list_active("asset")
    assert len(active) == 1 and active[0].version == 2


def test_cannot_start_second_draft_while_in_flight(service: ConfigService):
    service.create("asset", _asset_payload(), actor="eng")
    with pytest.raises(ConfigConflictError):
        service.create("asset", _asset_payload(), actor="eng", config_id="AST-HPP-01")


# --- audit ------------------------------------------------------------------


def test_audit_entry_emitted_on_every_state_change(service: ConfigService):
    store = service._store
    service.create("asset", _asset_payload(), actor="erin-engineer")
    service.publish("asset", "AST-HPP-01", actor="erin-engineer")
    active = service.approve("asset", "AST-HPP-01", actor="ada-admin")

    kinds = [e["kind"] for e in store.audit_chain_asc()]
    assert kinds == [
        "config.created",
        "config.submitted",
        "config.approved",
        "config.activated",
    ]

    # The audit trail is a valid hash chain and records the acting identity +
    # the version id as the subject.
    assert store.verify_chain()["ok"] is True
    events = store.audit_chain_asc()
    assert events[-1]["actor"] == "ada-admin"
    assert events[-1]["subject"] == active.version_id
    assert events[0]["payload"]["entity_type"] == "asset"


def test_supersede_emits_audit_entry(service: ConfigService):
    service.create("asset", _asset_payload(), actor="eng")
    service.publish("asset", "AST-HPP-01", actor="eng")
    service.approve("asset", "AST-HPP-01", actor="eng")
    service.create("asset", _asset_payload(), actor="eng", config_id="AST-HPP-01")
    service.publish("asset", "AST-HPP-01", actor="eng")
    service.approve("asset", "AST-HPP-01", actor="eng")

    kinds = [e["kind"] for e in service._store.audit_chain_asc()]
    assert "config.superseded" in kinds


# --- tag-map round-trip -----------------------------------------------------


def test_tag_mapping_round_trip_through_normalization(service: ConfigService):
    payload = {
        "customer_tag": "PLC1.HPP_A.WINDING_TEMP_F",
        "asset_id": "AST-HPP-01",
        "metric": "winding_temp_c",
        "unit": "degC",
        "scale": 0.5,
        "offset": -10.0,
        "sampling_frequency_s": 5.0,
    }
    service.create("tag_mapping", payload, actor="eng")
    service.publish("tag_mapping", "PLC1.HPP_A.WINDING_TEMP_F", actor="eng")
    service.approve("tag_mapping", "PLC1.HPP_A.WINDING_TEMP_F", actor="eng")

    tag_map = service.active_tag_map()
    assert "PLC1.HPP_A.WINDING_TEMP_F" in tag_map.entries

    result = normalize(
        [RawReading(customer_tag="PLC1.HPP_A.WINDING_TEMP_F", value=100.0)],
        tag_map,
    )
    assert not result.rejected
    reading = result.readings[0]
    assert reading.asset_id == "AST-HPP-01"
    assert reading.metric == "winding_temp_c"
    # canonical = raw * scale + offset = 100 * 0.5 - 10 = 40.0
    assert reading.value == pytest.approx(40.0)


# --- pump-curve validation ranges -------------------------------------------


def test_pump_curve_valid(service: ConfigService):
    created = service.create("pump_curve", _pump_curve_payload(), actor="eng")
    assert created.status.value == "draft"


def test_pump_curve_flow_must_be_strictly_increasing(service: ConfigService):
    bad = _pump_curve_payload()
    bad["points"][2]["flow_m3h"] = 120.0  # duplicate of previous flow
    with pytest.raises(ConfigValidationError):
        service.create("pump_curve", bad, actor="eng")


def test_pump_curve_head_must_not_rise_with_flow(service: ConfigService):
    bad = _pump_curve_payload()
    bad["points"][2]["head_m"] = 500.0  # head rises as flow rises
    with pytest.raises(ConfigValidationError):
        service.create("pump_curve", bad, actor="eng")


def test_pump_curve_requires_at_least_two_points(service: ConfigService):
    bad = _pump_curve_payload()
    bad["points"] = bad["points"][:1]
    with pytest.raises(ConfigValidationError):
        service.create("pump_curve", bad, actor="eng")


def test_pump_curve_efficiency_out_of_range(service: ConfigService):
    bad = _pump_curve_payload()
    bad["points"][1]["efficiency"] = 1.5
    with pytest.raises(ConfigValidationError):
        service.create("pump_curve", bad, actor="eng")


# --- membrane-model validation ranges ---------------------------------------


def test_membrane_model_valid(service: ConfigService):
    created = service.create("membrane_model", _membrane_payload(), actor="eng")
    assert created.status.value == "draft"


def test_membrane_salt_rejection_out_of_range(service: ConfigService):
    bad = _membrane_payload()
    bad["nominal_salt_rejection_pct"] = 101.0
    with pytest.raises(ConfigValidationError):
        service.create("membrane_model", bad, actor="eng")


def test_membrane_area_must_be_positive(service: ConfigService):
    bad = _membrane_payload()
    bad["active_area_m2"] = 0.0
    with pytest.raises(ConfigValidationError):
        service.create("membrane_model", bad, actor="eng")


def test_membrane_recovery_must_be_below_one(service: ConfigService):
    bad = _membrane_payload()
    bad["max_recovery"] = 1.2
    with pytest.raises(ConfigValidationError):
        service.create("membrane_model", bad, actor="eng")


def test_membrane_concentrate_flow_cannot_exceed_feed(service: ConfigService):
    bad = _membrane_payload()
    bad["min_concentrate_flow_m3h"] = 50.0  # > max_feed_flow_m3h
    with pytest.raises(ConfigValidationError):
        service.create("membrane_model", bad, actor="eng")


# --- RBAC (enforced auth) ---------------------------------------------------

TEST_ISSUER = "https://keycloak.test/realms/watertwin"


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
    private_pem, public_pem = rsa_keypair
    monkeypatch.setenv("WATERTWIN_AUTH_DISABLED", "false")
    monkeypatch.setenv("WATERTWIN_OIDC_PUBLIC_KEY", public_pem)
    monkeypatch.setenv("WATERTWIN_OIDC_ISSUER", TEST_ISSUER)
    monkeypatch.delenv("WATERTWIN_OIDC_AUDIENCE", raising=False)

    from app.main import app, store

    store.reset()

    def token(username: str, roles: list[str]) -> dict:
        return {
            "Authorization": f"Bearer {_make_token(private_pem, username=username, roles=roles)}"
        }

    with TestClient(app) as c:
        c.token = token  # type: ignore[attr-defined]
        yield c


def _seed_submitted(auth_client) -> None:
    """Create + publish an asset config as an engineer (ready for approval)."""
    r = auth_client.post(
        "/api/v1/config/asset",
        headers=auth_client.token("erin-engineer", ["engineer"]),
        json={"payload": _asset_payload()},
    )
    assert r.status_code == 200, r.text
    r = auth_client.post(
        "/api/v1/config/asset/AST-HPP-01/publish",
        headers=auth_client.token("erin-engineer", ["engineer"]),
    )
    assert r.status_code == 200, r.text


def test_viewer_cannot_create_config_403(auth_client):
    r = auth_client.post(
        "/api/v1/config/asset",
        headers=auth_client.token("val-viewer", ["viewer"]),
        json={"payload": _asset_payload()},
    )
    assert r.status_code == 403


def test_viewer_cannot_approve_403(auth_client):
    _seed_submitted(auth_client)
    r = auth_client.post(
        "/api/v1/config/asset/AST-HPP-01/approve",
        headers=auth_client.token("val-viewer", ["viewer"]),
    )
    assert r.status_code == 403


def test_operator_cannot_approve_403(auth_client):
    _seed_submitted(auth_client)
    r = auth_client.post(
        "/api/v1/config/asset/AST-HPP-01/approve",
        headers=auth_client.token("ola-operator", ["operator"]),
    )
    assert r.status_code == 403


def test_engineer_can_approve_and_identity_is_audited(auth_client):
    _seed_submitted(auth_client)
    r = auth_client.post(
        "/api/v1/config/asset/AST-HPP-01/approve",
        headers=auth_client.token("erin-engineer", ["engineer"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"

    events = auth_client.get(
        "/api/v1/audit", headers=auth_client.token("aud-auditor", ["auditor"])
    ).json()["events"]
    approved = next(e for e in events if e["kind"] == "config.approved")
    assert approved["actor"] == "erin-engineer"


def test_any_authenticated_role_may_read_config(auth_client):
    r = auth_client.get(
        "/api/v1/config/entities",
        headers=auth_client.token("val-viewer", ["viewer"]),
    )
    assert r.status_code == 200
    assert "asset" in r.json()["entities"]


def test_no_delete_endpoint_for_published_versions(auth_client):
    _seed_submitted(auth_client)
    auth_client.post(
        "/api/v1/config/asset/AST-HPP-01/approve",
        headers=auth_client.token("erin-engineer", ["engineer"]),
    )
    # There is no delete path -- published versions can only be superseded.
    r = auth_client.request(
        "DELETE",
        "/api/v1/config/asset/AST-HPP-01",
        headers=auth_client.token("ada-admin", ["admin"]),
    )
    assert r.status_code == 405


def test_config_response_keeps_read_only_control_boundary(auth_client):
    r = auth_client.get(
        "/api/v1/config/entities",
        headers=auth_client.token("val-viewer", ["viewer"]),
    )
    cb = r.json()["control_boundary"]
    assert cb["control_write_enabled"] is False
    assert cb["operator_approval_required"] is True
