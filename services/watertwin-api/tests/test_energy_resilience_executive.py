"""Tests for the value layer: Energy Optimization, Resilience & Generator
Command, and Executive Value / ROI.

Fast and dependency-free (no live hydraulic-sim): they exercise the read-only
endpoints, the constrained energy optimisation, the grid-outage resilience
assessment (including recommendation + audit routing), and the executive ROI
aggregation. Every value/ROI figure must be ESTIMATED, on a synthetic basis, and
carry the read-only control boundary; the executive responses must carry the
disclaimer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        yield c


_GET_ENDPOINTS = [
    "/api/v1/energy/summary",
    "/api/v1/energy/losses",
    "/api/v1/resilience/criticality",
    "/api/v1/resilience/generator",
    "/api/v1/executive/value-summary",
    "/api/v1/executive/roi",
]


@pytest.mark.parametrize("path", _GET_ENDPOINTS)
def test_endpoints_carry_boundary_and_provenance(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["control_boundary"]["control_write_enabled"] is False
    assert body["control_boundary"]["operator_approval_required"] is True
    assert body["provenance"] in {"estimated", "preliminary"}


# --- Energy -----------------------------------------------------------------


def test_energy_optimize_lowers_sec_and_respects_bounds(client):
    body = client.post("/api/v1/energy/optimize", json={}).json()
    opt = body["optimization"]
    assert body["provenance"] == "estimated"
    assert opt["provenance"] == "estimated"
    # Optimisation lowers specific energy versus the (off-optimal) baseline.
    assert opt["optimized_sec_kwh_m3"] < opt["baseline_sec_kwh_m3"]
    assert opt["sec_reduction_kwh_m3"] > 0.0
    # And never violates a constraint bound.
    assert opt["constraints_respected"] is True
    assert opt["binding_constraints"] == []
    assert 45.0 - 1e-6 <= opt["optimal_feed_pressure_bar"] <= 75.0 + 1e-6
    assert 0.35 - 1e-6 <= opt["optimal_recovery"] <= 0.52 + 1e-6
    assert opt["permeate_tds_mg_l"] <= 500.0 + 1e-6
    assert opt["permeate_boron_mg_l"] <= 1.0 + 1e-6


def test_energy_summary_renders_optimal_setpoint(client):
    body = client.get("/api/v1/energy/summary").json()
    assert body["energy_by_asset"]
    assert body["optimal_setpoint"]["feed_pressure_bar"] > 0
    assert body["optimal_setpoint"]["sec_kwh_m3"] <= body["current_setpoint"]["sec_kwh_m3"]


def test_energy_losses_are_estimated(client):
    body = client.get("/api/v1/energy/losses").json()
    assert body["losses"]
    for loss in body["losses"]:
        assert loss["provenance"] == "estimated"
        assert loss["avoidable_loss_kwh_m3"] >= 0.0


# --- Resilience -------------------------------------------------------------


def test_resilience_criticality_orders_hp_pump_first(client):
    body = client.get("/api/v1/resilience/criticality").json()
    ranking = body["criticality"]
    assert ranking
    assert ranking[0]["asset_id"] == "AST-HPP-01"
    scores = [c["criticality_score"] for c in ranking]
    assert scores == sorted(scores, reverse=True)


def test_resilience_generator_start_probability_in_range_and_preliminary(client):
    gen = client.get("/api/v1/resilience/generator").json()["generator"]
    assert 0.0 <= gen["start_probability"] <= 1.0
    assert gen["provenance"] == "preliminary"
    assert gen["fuel_endurance_hours"] > 0.0


def test_grid_outage_shed_plan_keeps_hp_pump_last(client):
    body = client.post("/api/v1/resilience/grid-outage", json={}).json()
    plan = body["load_shed_plan"]
    items = plan["items"]
    assert items
    max_order = max(i["shed_order"] for i in items)
    hp = next(i for i in items if i["asset_id"] == "AST-HPP-01")
    assert hp["shed_order"] == max_order
    assert hp["retained"] is True
    assert body["service_continuity"]["service_continuity_hours"] > 0.0


def test_grid_outage_recommendation_pending_and_write_disabled(client):
    body = client.post("/api/v1/resilience/grid-outage", json={}).json()
    rec = body["recommendation"]
    assert rec["approval_status"] == "pending"
    assert rec["control_boundary"]["control_write_enabled"] is False
    assert rec["control_boundary"]["operator_approval_required"] is True

    # Routed through the existing recommendation + audit path.
    events = client.get("/api/v1/audit").json()["events"]
    assert any(e["kind"] == "resilience.recommendation.created" for e in events)
    listed = client.get("/api/v1/recommendations").json()
    assert any(r["recommendation_id"] == "rec-resilience-grid-outage" for r in listed)


def test_grid_outage_routing_is_idempotent(client):
    client.post("/api/v1/resilience/grid-outage", json={})
    client.post("/api/v1/resilience/grid-outage", json={})
    recs = client.get("/api/v1/recommendations").json()
    matches = [r for r in recs if r["recommendation_id"] == "rec-resilience-grid-outage"]
    assert len(matches) == 1


# --- Executive --------------------------------------------------------------


def test_executive_value_summary_aggregates_estimated_with_disclaimer(client):
    body = client.get("/api/v1/executive/value-summary").json()
    assert "disclaimer" in body and body["disclaimer"]
    assert "not validated savings" in body["disclaimer"].lower()
    summary = body["value_summary"]
    assert summary["provenance"] == "estimated"
    assert summary["synthetic_basis"] is True
    # Every component and the aggregate are ESTIMATED.
    assert summary["components"]
    for comp in summary["components"]:
        assert comp["provenance"] == "estimated"
    # The total aggregates the components.
    total = sum(c["annualized_benefit"] for c in summary["components"])
    assert summary["total_annualized_benefit"] == pytest.approx(total, rel=1e-6)
    # All six benefit categories are present.
    for field in (
        "downtime_avoided",
        "energy_savings",
        "chemical_savings",
        "water_loss_avoided",
        "maintenance_savings",
        "capex_deferred",
    ):
        assert field in summary


def test_executive_roi_is_estimated_with_disclaimer(client):
    body = client.get("/api/v1/executive/roi").json()
    assert "disclaimer" in body and body["disclaimer"]
    roi = body["roi"]
    assert roi["provenance"] == "estimated"
    assert roi["synthetic_basis"] is True
    for field in ("pilot_roi_pct", "annualized_benefit", "payback_period_months"):
        assert field in roi
    # ROI is consistent with the aggregated annualized benefit.
    summary = client.get("/api/v1/executive/value-summary").json()["value_summary"]
    assert roi["annualized_benefit"] == pytest.approx(
        summary["total_annualized_benefit"], rel=1e-6
    )
