"""Tests for the work-order / Maintenance Center capability.

Fast and dependency-free (no live hydraulic-sim). They lock the decision-relevant
invariants of the maintenance work-order flow:

* work orders are DERIVED from predictive-maintenance alerts and are traceable
  to the originating model + evidence,
* the default CMMS adapter is strictly READ-ONLY (pull work orders / asset
  history; write-back refused),
* proposed work orders are created ``pending`` and audited on creation, approval
  is a separate audited operator action, and
* write-back is gated behind a config flag, routes only through operator
  approval, and is a CMMS ticket -- never a control/OT path.
"""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

from canonical_water_model import ApprovalStatus, WorkOrderStatus
from app import cmms as cmms_pkg
from app import maintenance
from app import predictive_maintenance as pdm
from app.cmms.base import CmmsWriteNotEnabled
from app.cmms.readonly import ReadOnlyCmmsAdapter
from app.cmms.writeback import WriteBackCmmsAdapter
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        # Default to the read-only adapter for each test unless overridden.
        app.state.cmms_adapter = ReadOnlyCmmsAdapter()
        c.post("/api/v1/reset")
        yield c
        app.state.cmms_adapter = None


# --- Alert -> work-order traceability (engine) ------------------------------


def test_work_order_is_traceable_to_originating_pdm_alert():
    recs = pdm.compute_recommendations(0.6)
    assert recs
    rec = recs[0]
    wo = maintenance.build_work_order_from_pdm(rec)

    # Traceable to the exact model artifact it came from.
    assert wo.originating_model == "predictive-maintenance"
    assert wo.source_recommendation_id == rec.recommendation_id
    assert wo.source_alert_code == f"PDM-{rec.asset_id}"
    assert wo.asset_id == rec.asset_id
    assert wo.predicted_failure_mode == rec.predicted_failure_mode

    # Evidence + ranked causes are carried for traceability.
    assert wo.evidence is not None
    assert wo.evidence.assets_reviewed == [rec.asset_id]
    assert wo.ranked_causes, "ranked root causes must be attached as evidence"

    # Created pending, advisory only, no control write.
    assert wo.approval_status == ApprovalStatus.pending
    assert wo.status == WorkOrderStatus.proposed
    assert wo.control_boundary.control_write_enabled is False
    assert wo.control_boundary.operator_approval_required is True
    assert wo.provenance.value == "preliminary"


def test_higher_failure_probability_yields_higher_priority():
    order = {"low": 0, "medium": 1, "high": 2, "urgent": 3}
    wos = maintenance.propose_work_orders(0.6)
    assert wos
    for wo in wos:
        p = wo.failure_probability_30d or 0.0
        if p >= 0.6:
            assert wo.priority.value == "urgent"
        elif p >= 0.35:
            assert wo.priority.value in {"high", "urgent"}
    # And priorities are consistent with the ranking (highest risk first).
    assert order[wos[0].priority.value] >= order[wos[-1].priority.value]


# --- Endpoint: derive + list, traceability + boundary -----------------------


def test_work_orders_endpoint_derives_traceable_pending_orders(client):
    body = client.get("/api/v1/maintenance/work-orders").json()
    assert body["control_boundary"]["control_write_enabled"] is False
    assert body["control_boundary"]["operator_approval_required"] is True

    orders = body["work_orders"]
    assert orders
    for wo in orders:
        assert wo["originating_model"] == "predictive-maintenance"
        assert wo["source_recommendation_id"]
        assert wo["approval_status"] == "pending"
        assert wo["status"] == "proposed"
        assert wo["control_boundary"]["control_write_enabled"] is False

    # The source recommendation card exists and is retrievable (link resolves).
    listed = {r["recommendation_id"] for r in client.get("/api/v1/recommendations").json()}
    for wo in orders:
        assert wo["source_recommendation_id"] in listed


def test_work_order_creation_is_audited(client):
    client.get("/api/v1/maintenance/work-orders")
    events = client.get("/api/v1/audit").json()["events"]
    created = [e for e in events if e["kind"] == "workorder.created"]
    assert created
    # The audit payload carries the model traceability.
    assert all(e["payload"].get("originating_model") == "predictive-maintenance" for e in created)
    assert all(e["payload"].get("source_recommendation_id") for e in created)


def test_work_order_derivation_is_idempotent(client):
    first = client.get("/api/v1/maintenance/work-orders").json()["work_orders"]
    second = client.get("/api/v1/maintenance/work-orders").json()["work_orders"]
    ids_first = sorted(w["work_order_id"] for w in first)
    ids_second = sorted(w["work_order_id"] for w in second)
    assert ids_first == ids_second
    assert len(ids_second) == len(set(ids_second))
    # Only one creation audit event per work order.
    events = client.get("/api/v1/audit").json()["events"]
    created = [e for e in events if e["kind"] == "workorder.created"]
    assert len(created) == len(set(e["subject"] for e in created))


# --- Approval + audit -------------------------------------------------------


def test_approval_updates_status_and_is_audited(client):
    orders = client.get("/api/v1/maintenance/work-orders").json()["work_orders"]
    wo_id = orders[0]["work_order_id"]

    resp = client.post(
        f"/api/v1/maintenance/work-orders/{wo_id}/decision",
        json={"status": "approved", "actor": "alice"},
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()["work_order"]
    assert updated["approval_status"] == "approved"
    assert updated["status"] == "approved"
    assert updated["approved_by"] == "alice"
    assert updated["decided_at"]
    # Approval is never a control write.
    assert updated["control_boundary"]["control_write_enabled"] is False

    events = client.get("/api/v1/audit").json()["events"]
    assert any(
        e["kind"] == "workorder.decision" and e["subject"] == wo_id for e in events
    )


def test_reject_decision_sets_rejected(client):
    orders = client.get("/api/v1/maintenance/work-orders").json()["work_orders"]
    wo_id = orders[0]["work_order_id"]
    resp = client.post(
        f"/api/v1/maintenance/work-orders/{wo_id}/decision",
        json={"status": "rejected"},
    )
    assert resp.status_code == 200
    assert resp.json()["work_order"]["status"] == "rejected"


def test_invalid_decision_rejected(client):
    orders = client.get("/api/v1/maintenance/work-orders").json()["work_orders"]
    wo_id = orders[0]["work_order_id"]
    resp = client.post(
        f"/api/v1/maintenance/work-orders/{wo_id}/decision", json={"status": "maybe"}
    )
    assert resp.status_code == 422


def test_unknown_work_order_returns_404(client):
    assert client.get("/api/v1/maintenance/work-orders/wo-nope").status_code == 404
    resp = client.post(
        "/api/v1/maintenance/work-orders/wo-nope/decision", json={"status": "approved"}
    )
    assert resp.status_code == 404


# --- CMMS adapter: read-only default ----------------------------------------


def test_default_cmms_adapter_is_read_only():
    adapter = cmms_pkg.resolve_cmms_adapter(_Config(write_back=False))
    assert isinstance(adapter, ReadOnlyCmmsAdapter)
    assert adapter.write_enabled is False
    desc = adapter.describe()
    assert desc["read_only"] is True
    assert desc["write_back_is_control_path"] is False


def test_read_only_adapter_pulls_but_refuses_write():
    adapter = ReadOnlyCmmsAdapter()
    assert adapter.pull_work_orders()  # non-empty synthetic pull
    assert adapter.pull_asset_history("AST-HPP-01")
    assert adapter.pull_asset_history("AST-UNKNOWN") == []

    wos = maintenance.propose_work_orders(0.6)
    wos[0].approval_status = ApprovalStatus.approved
    with pytest.raises(CmmsWriteNotEnabled):
        adapter.create_work_order(wos[0], approved=True)


def test_cmms_status_and_pull_endpoints_are_read_only(client):
    status = client.get("/api/v1/maintenance/cmms/status").json()
    assert status["cmms"]["read_only"] is True
    assert status["control_boundary"]["control_write_enabled"] is False

    orders = client.get("/api/v1/maintenance/cmms/work-orders").json()
    assert orders["work_orders"]
    assert all(w["source"] == "cmms" for w in orders["work_orders"])

    history = client.get("/api/v1/maintenance/cmms/asset-history/AST-HPP-01").json()
    assert history["asset_id"] == "AST-HPP-01"
    assert history["history"]


def test_read_only_decision_does_not_create_cmms_ticket(client):
    orders = client.get("/api/v1/maintenance/work-orders").json()["work_orders"]
    wo_id = orders[0]["work_order_id"]
    updated = client.post(
        f"/api/v1/maintenance/work-orders/{wo_id}/decision", json={"status": "approved"}
    ).json()["work_order"]
    # No CMMS ticket under the read-only adapter.
    assert updated["cmms_sync_status"] == "not_synced"
    assert updated["cmms_external_id"] is None
    events = client.get("/api/v1/audit").json()["events"]
    assert not any(e["kind"] == "workorder.cmms.ticket_created" for e in events)


# --- CMMS adapter: write-back (behind flag, approval-gated, not a control path)


def test_write_back_requires_operator_approval():
    adapter = WriteBackCmmsAdapter()
    assert adapter.write_enabled is True
    wo = maintenance.propose_work_orders(0.6)[0]
    # Unapproved -> refused, even on a write-enabled adapter.
    assert wo.approval_status == ApprovalStatus.pending
    with pytest.raises(CmmsWriteNotEnabled):
        adapter.create_work_order(wo, approved=False)
    with pytest.raises(CmmsWriteNotEnabled):
        adapter.create_work_order(wo, approved=True)  # status still pending


def test_write_back_creates_ticket_only_after_approval_and_is_not_a_control_path():
    adapter = WriteBackCmmsAdapter()
    wo = maintenance.propose_work_orders(0.6)[0]
    wo.approval_status = ApprovalStatus.approved
    ticket = adapter.create_work_order(wo, approved=True)
    assert ticket.cmms_sync_status.value == "synced"
    assert ticket.cmms_external_id
    assert ticket.cmms_system
    # A ticket is not a control command: the control boundary stays read-only.
    assert ticket.control_boundary.control_write_enabled is False
    assert ticket.control_boundary.operator_approval_required is True


def test_approval_writes_back_ticket_when_flag_enabled(client):
    # Enable write-back for this test by injecting a write-back adapter.
    app.state.cmms_adapter = WriteBackCmmsAdapter()
    orders = client.get("/api/v1/maintenance/work-orders").json()["work_orders"]
    wo_id = orders[0]["work_order_id"]
    updated = client.post(
        f"/api/v1/maintenance/work-orders/{wo_id}/decision", json={"status": "approved"}
    ).json()["work_order"]

    assert updated["cmms_sync_status"] == "synced"
    assert updated["cmms_external_id"]
    # Still not a control path.
    assert updated["control_boundary"]["control_write_enabled"] is False

    events = client.get("/api/v1/audit").json()["events"]
    ticket_events = [e for e in events if e["kind"] == "workorder.cmms.ticket_created"]
    assert ticket_events
    assert ticket_events[0]["payload"]["is_control_path"] is False


def test_config_resolves_write_back_only_when_flag_set():
    assert isinstance(cmms_pkg.resolve_cmms_adapter(_Config(False)), ReadOnlyCmmsAdapter)
    assert isinstance(cmms_pkg.resolve_cmms_adapter(_Config(True)), WriteBackCmmsAdapter)


# --- Read-only boundary guard for the CMMS package --------------------------

CMMS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "cmms")

#: A CMMS ticket write is fine; an OT/control write is never allowed here.
_FORBIDDEN_CONTROL_PATTERNS = [
    r"control_write_enabled\s*=\s*True",
    r"\bwrite_coil\b",
    r"\bwrite_register\b",
    r"\bwrite_value\b",
    r"\bset_value\b",
]


def test_cmms_package_has_no_control_write_path():
    files = [
        os.path.join(CMMS_DIR, f) for f in os.listdir(CMMS_DIR) if f.endswith(".py")
    ]
    assert files
    offenders: list[str] = []
    for path in files:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        for pattern in _FORBIDDEN_CONTROL_PATTERNS:
            if re.search(pattern, text):
                offenders.append(f"{os.path.basename(path)} matches {pattern!r}")
    assert not offenders, "Forbidden control-write path in app/cmms/: " + "; ".join(offenders)


class _Config:
    """Minimal config stand-in for adapter resolution."""

    def __init__(self, write_back: bool) -> None:
        self.CMMS_WRITE_BACK_ENABLED = write_back
        self.CMMS_SYSTEM_NAME = "test-cmms"
