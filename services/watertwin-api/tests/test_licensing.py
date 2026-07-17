"""Licensing / entitlement-layer tests.

These lock the two properties the work package requires:

* **Entitlement gate** — a plan that does not include a feature refuses the
  gated endpoint with 402, while an included feature is served.
* **Feature-gating never touches the safety invariant** — even the smallest
  plan leaves the advisory/read-only control boundary intact.

They run under the default dev-auth bypass (see ``conftest.py``); the gate is a
tenant/plan concern independent of authentication.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import licensing
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# --- Default plan -----------------------------------------------------------


def test_default_plan_is_enterprise_with_all_features(client):
    body = client.get("/api/v1/admin/entitlements").json()
    ent = body["entitlements"]
    assert ent["plan"] == "enterprise"
    assert set(ent["enabled_features"]) == set(licensing.ALL_FEATURES)
    assert body["safety_invariant_intact"] is True


def test_default_plan_serves_gated_endpoints(client):
    # With no plan configured (enterprise), every gated feature is available.
    assert client.get("/api/v1/energy/summary").status_code == 200
    assert client.get("/api/v1/water-quality/status").status_code == 200
    assert client.get("/api/v1/executive/roi").status_code == 200


# --- Entitlement gate -------------------------------------------------------


def test_restricted_plan_gates_unincluded_feature_402(client, monkeypatch):
    # 'standard' includes water_quality + predictive_maintenance, NOT energy /
    # resilience / executive / assistant.
    monkeypatch.setenv("WATERTWIN_PLAN", "standard")

    gated = client.get("/api/v1/energy/summary")
    assert gated.status_code == 402
    assert "energy_optimization" in gated.json()["detail"]

    # An included feature is still served under the same restricted plan.
    assert client.get("/api/v1/water-quality/status").status_code == 200


def test_starter_plan_gates_predictive_maintenance(client, monkeypatch):
    monkeypatch.setenv("WATERTWIN_PLAN", "starter")
    assert client.get("/api/v1/equipment/AST-HPP-01/health").status_code == 402
    # starter still includes water_quality.
    assert client.get("/api/v1/water-quality/status").status_code == 200


def test_custom_license_json_overrides_features(client, monkeypatch):
    monkeypatch.setenv(
        "WATERTWIN_LICENSE",
        json.dumps(
            {
                "tenant_id": "acme-water",
                "plan": "custom",
                "features": ["water_quality"],
                "limits": {"max_assets": 3},
            }
        ),
    )
    ent = client.get("/api/v1/admin/entitlements").json()["entitlements"]
    assert ent["tenant_id"] == "acme-water"
    assert ent["plan"] == "custom"
    assert ent["enabled_features"] == ["water_quality"]
    assert ent["limits"]["max_assets"] == 3

    assert client.get("/api/v1/water-quality/status").status_code == 200
    assert client.get("/api/v1/energy/summary").status_code == 402


def test_unknown_plan_falls_back_to_enterprise(client, monkeypatch):
    monkeypatch.setenv("WATERTWIN_PLAN", "does-not-exist")
    ent = client.get("/api/v1/admin/entitlements").json()["entitlements"]
    assert ent["plan"] == "enterprise"


# --- Safety invariant is never touched by feature-gating --------------------


def test_feature_gate_never_relaxes_safety_invariant(client, monkeypatch):
    # Even the most restrictive plan leaves the advisory/read-only boundary.
    monkeypatch.setenv("WATERTWIN_PLAN", "starter")

    # A gated feature is refused with 402 (a billing signal) ...
    assert client.get("/api/v1/energy/summary").status_code == 402

    # ... and the control boundary is unchanged everywhere.
    health = client.get("/health").json()
    assert health["control_write_enabled"] is False
    assert health["operator_approval_required"] is True
    assert health["control_mode"] == "advisory"

    ent_body = client.get("/api/v1/admin/entitlements").json()
    assert ent_body["safety_invariant_intact"] is True
    assert ent_body["control_boundary"]["control_write_enabled"] is False


def test_safety_invariant_function_holds():
    assert licensing.safety_invariant_intact() is True


def test_no_plan_can_enable_control_write():
    # Exhaustively: no plan's feature set could ever imply a control-write path;
    # the control boundary is a fixed advisory default independent of plans.
    for plan in licensing.PLANS.values():
        assert "control_write_enabled" not in plan.features
    assert licensing.safety_invariant_intact() is True
