"""Tests for the Condition-Intelligence service layer + endpoints.

Fast and dependency-free (no live hydraulic-sim). They exercise the governed
model registry, the back-test / calibration / drift endpoints, and the
operator-feedback capture round-trip through the durable store. They lock the
decision-relevant invariants: every model publishes its full contract, the drift
flag fires on the shifted live window, feedback confirm/dismiss is persisted and
audited, and every response carries the control boundary + provenance.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import condition
from app.main import app
from app.store import Store


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        yield c


# --- Governed model registry + published contract ---------------------------


def test_every_model_publishes_a_complete_contract() -> None:
    assert condition.list_model_ids()
    for model_id in condition.list_model_ids():
        # Building the spec dict never raises, and validation passes.
        bundle = condition.MODELS[model_id]
        bundle.model.spec.validate()
        spec = condition.model_spec_dict(model_id)
        for field in (
            "equation_source",
            "feature_spec",
            "assumptions",
            "valid_range",
            "version",
            "uncertainty_method",
            "failure_modes",
            "explainability_outputs",
        ):
            assert spec[field], f"{model_id} missing {field}"


def test_models_endpoint_lists_contracts(client) -> None:
    r = client.get("/api/v1/condition/models")
    assert r.status_code == 200
    body = r.json()
    assert body["control_boundary"]["control_write_enabled"] is False
    assert body["provenance"] == "preliminary"
    assert len(body["models"]) == len(condition.list_model_ids())


def test_spec_endpoint_unknown_model_404(client) -> None:
    assert client.get("/api/v1/condition/models/nope/spec").status_code == 404


# --- Back-test / calibration / drift endpoints ------------------------------


def test_backtest_endpoint_returns_metrics(client) -> None:
    model_id = condition.list_model_ids()[0]
    r = client.get(f"/api/v1/condition/models/{model_id}/backtest")
    assert r.status_code == 200
    m = r.json()["backtest"]["metrics"]
    for key in ("precision", "recall", "false_alarm_rate", "mean_lead_time"):
        assert key in m
    assert 0.0 <= m["precision"] <= 1.0
    assert 0.0 <= m["recall"] <= 1.0
    # Metrics carry their own uncertainty (Wilson intervals).
    lo, hi = m["precision_ci"]
    assert lo <= m["precision"] <= hi


def test_calibration_endpoint_returns_report(client) -> None:
    model_id = condition.list_model_ids()[0]
    r = client.get(f"/api/v1/condition/models/{model_id}/calibration")
    assert r.status_code == 200
    cal = r.json()["calibration"]
    assert 0.0 <= cal["ece"] <= 1.0
    assert 0.0 <= cal["brier"] <= 1.0
    assert cal["provenance"] == "preliminary"


def test_drift_endpoint_flags_shifted_and_clears_unshifted(client) -> None:
    model_id = condition.list_model_ids()[0]
    shifted = client.get(f"/api/v1/condition/models/{model_id}/drift").json()["drift"]
    assert shifted["drift_flag"] is True
    assert shifted["max_psi"] >= shifted["psi_threshold"]

    clear = client.get(
        f"/api/v1/condition/models/{model_id}/drift", params={"shifted": "false"}
    ).json()["drift"]
    assert clear["drift_flag"] is False


# --- Operator-feedback capture: store round-trip ----------------------------


def test_store_feedback_round_trip() -> None:
    store = Store(database_url=None, connect=False)
    rec = store.record_feedback(
        "alert-dp-01",
        "confirm",
        model_id="normalized-dp-fouling",
        asset_id="AST-MEMB-01",
        note="operator confirmed fouling on inspection",
    )
    assert rec["decision"] == "confirm"
    assert rec["feedback_id"]

    store.record_feedback("alert-dp-01", "dismiss", actor="op-2")

    for_alert = store.feedback_for("alert-dp-01")
    assert len(for_alert) == 2
    assert [f["decision"] for f in for_alert] == ["confirm", "dismiss"]

    recent = store.recent_feedback()
    assert recent[0]["decision"] == "dismiss"  # newest first


def test_store_feedback_rejects_bad_decision() -> None:
    store = Store(database_url=None, connect=False)
    with pytest.raises(ValueError):
        store.record_feedback("alert-x", "maybe")


def test_store_reset_clears_feedback() -> None:
    store = Store(database_url=None, connect=False)
    store.record_feedback("alert-x", "confirm")
    store.reset()
    assert store.recent_feedback() == []


# --- Operator-feedback capture: endpoint round-trip -------------------------


def test_feedback_endpoint_round_trip_and_audit(client) -> None:
    post = client.post(
        "/api/v1/condition/alerts/alert-dp-01/feedback",
        json={
            "decision": "confirm",
            "model_id": "normalized-dp-fouling",
            "asset_id": "AST-MEMB-01",
            "note": "confirmed on CIP",
        },
    )
    assert post.status_code == 200
    body = post.json()
    assert body["feedback"]["decision"] == "confirm"
    assert body["control_boundary"]["control_write_enabled"] is False

    listing = client.get(
        "/api/v1/condition/feedback", params={"alert_id": "alert-dp-01"}
    ).json()
    assert len(listing["feedback"]) == 1
    assert listing["feedback"][0]["alert_id"] == "alert-dp-01"

    # The decision is captured in the tamper-evident audit trail.
    audit = client.get("/api/v1/audit").json()["events"]
    assert any(e["kind"] == "condition.feedback.recorded" for e in audit)


def test_feedback_endpoint_rejects_bad_decision(client) -> None:
    r = client.post(
        "/api/v1/condition/alerts/alert-y/feedback",
        json={"decision": "not-a-decision"},
    )
    assert r.status_code == 422
