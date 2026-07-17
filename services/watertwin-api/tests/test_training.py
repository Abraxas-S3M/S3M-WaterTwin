"""Tests for the Operator Training Simulator (SIMULATION, sandboxed, read-only).

Fast and dependency-free (no live hydraulic-sim): they exercise the read-only
training endpoints, scenario injection off the existing synthetic telemetry +
scenario engines, rubric scoring, the durable training record, and -- most
importantly -- the sandbox isolation guarantee: the training sandbox CANNOT emit
any command and there is no control-write path anywhere in the training module.
Every response must carry the read-only control boundary, ``provenance =
"simulated"`` and the SIMULATION disclaimer.
"""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import training


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        yield c


# --- Scenario catalog + injection ------------------------------------------


def test_scenarios_cover_the_four_reference_drills(client):
    body = client.get("/api/v1/training/scenarios").json()
    assert body["provenance"] == "simulated"
    assert body["simulation"] is True
    assert body["control_boundary"]["control_write_enabled"] is False
    types = {s["scenario_type"] for s in body["scenarios"]}
    assert types == {"pump_degradation", "leak", "outage", "storm_power_loss"}
    # Rubric keywords are internal scoring detail and must not leak to the trainee.
    for scenario in body["scenarios"]:
        assert scenario["rubric"]
        for item in scenario["rubric"]:
            assert "keywords" not in item


@pytest.mark.parametrize(
    "scenario_id",
    ["pump-degradation", "leak", "outage", "storm-power-loss"],
)
def test_inject_scenario_opens_a_simulated_session(client, scenario_id):
    body = client.post(
        "/api/v1/training/sessions", json={"scenario_id": scenario_id, "operator": "trainee-1"}
    ).json()
    assert body["provenance"] == "simulated"
    assert body["simulation"] is True
    assert "SIMULATION" in body["disclaimer"]
    assert body["control_boundary"]["control_write_enabled"] is False

    session = body["session"]
    assert session["status"] == "in_progress"
    assert session["operator"] == "trainee-1"
    # The injected twin snapshot reuses the existing telemetry engine and is
    # tagged simulated (never presented as measured plant data).
    assert session["injected_telemetry"]
    for reading in session["injected_telemetry"]:
        assert reading["provenance"] == "simulated"
    assert session["twin_summary"]["headline"]


def test_inject_unknown_scenario_is_404(client):
    resp = client.post("/api/v1/training/sessions", json={"scenario_id": "nope"})
    assert resp.status_code == 404


# --- Action capture + scoring ----------------------------------------------


def _start(client, scenario_id="pump-degradation", operator="trainee-1"):
    return client.post(
        "/api/v1/training/sessions",
        json={"scenario_id": scenario_id, "operator": operator},
    ).json()["session"]


def test_capture_action_is_sandboxed_and_never_a_command(client):
    session_id = _start(client)["session_id"]
    body = client.post(
        f"/api/v1/training/sessions/{session_id}/actions",
        json={"kind": "diagnosis", "text": "Rising vibration on the bearing."},
    ).json()
    action = body["action"]
    assert action["sandboxed"] is True
    assert action["emitted_command"] is False
    assert body["session"]["actions"]
    assert body["control_boundary"]["control_write_enabled"] is False


def test_invalid_action_kind_is_422(client):
    session_id = _start(client)["session_id"]
    resp = client.post(
        f"/api/v1/training/sessions/{session_id}/actions",
        json={"kind": "command", "text": "open valve"},
    )
    assert resp.status_code == 422


def test_strong_response_passes_and_records_are_stored(client):
    session_id = _start(client)["session_id"]
    for text in (
        "High vibration and bearing wear detected on the HP pump.",
        "Efficiency drift indicates progressive degradation.",
        "Schedule a vibration diagnostic and bearing inspection in a low-demand window.",
        "Advisory only — recommend to operator for approval, no control write.",
    ):
        client.post(
            f"/api/v1/training/sessions/{session_id}/actions",
            json={"kind": "action", "text": text},
        )

    body = client.post(f"/api/v1/training/sessions/{session_id}/submit").json()
    record = body["record"]
    score = record["score"]
    assert body["provenance"] == "simulated"
    assert score["passed"] is True
    assert score["percentage"] == pytest.approx(100.0)
    assert score["band"] == "Exemplary"
    assert all(item["matched"] for item in score["items"])
    assert record["simulation"] is True
    assert record["control_boundary"]["control_write_enabled"] is False

    # The record is persisted and listable.
    records = client.get("/api/v1/training/records").json()["records"]
    assert any(r["record_id"] == record["record_id"] for r in records)


def test_weak_response_fails_with_actionable_feedback(client):
    session_id = _start(client)["session_id"]
    client.post(
        f"/api/v1/training/sessions/{session_id}/actions",
        json={"kind": "note", "text": "Not sure what is happening."},
    )
    body = client.post(f"/api/v1/training/sessions/{session_id}/submit").json()
    score = body["record"]["score"]
    assert score["passed"] is False
    assert score["percentage"] < training.PASS_THRESHOLD_PCT
    missed = [item for item in score["items"] if not item["matched"]]
    assert missed and all(item["feedback"].startswith("Missed") for item in missed)


def test_rubric_key_credits_the_matching_item(client):
    session = _start(client, scenario_id="leak")
    session_id = session["session_id"]
    # Target a rubric item by key without using any keyword text.
    client.post(
        f"/api/v1/training/sessions/{session_id}/actions",
        json={"kind": "action", "text": "Handled per procedure.", "rubric_key": "detect_leak"},
    )
    body = client.post(f"/api/v1/training/sessions/{session_id}/submit").json()
    items = {i["key"]: i for i in body["record"]["score"]["items"]}
    assert items["detect_leak"]["matched"] is True


def test_lifecycle_events_are_audited(client):
    session_id = _start(client)["session_id"]
    client.post(
        f"/api/v1/training/sessions/{session_id}/actions",
        json={"kind": "diagnosis", "text": "vibration"},
    )
    client.post(f"/api/v1/training/sessions/{session_id}/submit")
    kinds = {e["kind"] for e in client.get("/api/v1/audit").json()["events"]}
    assert "training.session.started" in kinds
    assert "training.action.captured" in kinds
    assert "training.session.scored" in kinds


# --- Sandbox isolation guard -----------------------------------------------


def test_sandbox_cannot_emit_a_command():
    """The sandbox must refuse to emit any command (no control-write path)."""
    sandbox = training.TrainingSandbox()
    assert sandbox.is_simulation is True
    assert sandbox.control_write_enabled is False
    assert sandbox.can_emit_command is False
    with pytest.raises(training.SandboxViolationError):
        sandbox.emit_command("open", "valve-1")
    # A recorded action is captured but is never a command.
    action = sandbox.record_action("action", "isolate segment")
    assert action.emitted_command is False
    assert action.sandboxed is True


#: Forbidden control-write call patterns. If any appears in app/training.py a
#: control-write / OT path may have been introduced and this test fails the
#: build (mirrors the OT-sources and CI boundary guards).
_FORBIDDEN_PATTERNS = [
    r"control_write_enabled\s*=\s*True",
    # OPC UA / OT node writes.
    r"\bwrite_value\b",
    r"\bwrite_values\b",
    r"\bset_value\b",
    r"\bwrite_attribute\b",
    # Modbus write function codes.
    r"\bwrite_coil\b",
    r"\bwrite_coils\b",
    r"\bwrite_register\b",
    r"\bwrite_registers\b",
    # Generic control-emit verbs.
    r"\bsend_command\b",
    r"\bissue_command\b",
    r"\bactuate\b",
    r"\bsetpoint_write\b",
]

_TRAINING_MODULE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "training.py")


def test_training_module_has_no_control_write_path():
    with open(_TRAINING_MODULE, "r", encoding="utf-8") as fh:
        text = fh.read()
    offenders = [p for p in _FORBIDDEN_PATTERNS if re.search(p, text)]
    assert not offenders, (
        "Forbidden control-write path detected in app/training.py: " + "; ".join(offenders)
    )


def test_every_training_endpoint_carries_the_readonly_boundary(client):
    session = _start(client)
    session_id = session["session_id"]
    client.post(
        f"/api/v1/training/sessions/{session_id}/actions",
        json={"kind": "note", "text": "note"},
    )
    paths = [
        ("GET", "/api/v1/training/scenarios", None),
        ("GET", f"/api/v1/training/sessions/{session_id}", None),
        ("POST", f"/api/v1/training/sessions/{session_id}/submit", {}),
        ("GET", "/api/v1/training/records", None),
    ]
    for method, path, payload in paths:
        resp = client.get(path) if method == "GET" else client.post(path, json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["simulation"] is True
        assert body["provenance"] == "simulated"
        assert body["control_boundary"]["control_write_enabled"] is False
        assert body["control_boundary"]["operator_approval_required"] is True
