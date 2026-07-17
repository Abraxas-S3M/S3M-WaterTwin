"""Tests for Equipment & Membrane Intelligence + Predictive Maintenance.

Fast and dependency-free (no live hydraulic-sim): they exercise the membrane
engine (which reuses the WQ layer), the PdM ranking, and the eight read-only
endpoints. They lock the decision-relevant invariants: membrane health falls and
CIP is flagged as fouling rises, the ranking orders higher-risk assets first,
every PdM recommendation is created pending with control write disabled, and
every response carries the control boundary + provenance.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import membrane
from app import predictive_maintenance as pdm
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        yield c


# --- Membrane engine (reuses the WQ layer) ---------------------------------


def test_membrane_health_falls_as_fouling_rises():
    clean = membrane.compute_membrane_health(0.0)
    fouled = membrane.compute_membrane_health(0.85)
    assert fouled.score < clean.score
    # The reused normalized WQ signals both rise with fouling.
    assert fouled.normalized_salt_passage_rise_pct > clean.normalized_salt_passage_rise_pct
    assert fouled.normalized_dp_rise_pct > clean.normalized_dp_rise_pct


def test_fouling_tick_raises_severity_and_flags_cip():
    clean = membrane.compute_membrane_health(0.0)
    fouled = membrane.compute_membrane_health(0.9)
    assert fouled.fouling.organic >= clean.fouling.organic
    assert fouled.fouling.scaling >= clean.fouling.scaling
    assert fouled.cleaning_required is True
    assert fouled.cleaning_reason
    # A specific vessel/element is identified as underperforming.
    assert fouled.underperforming_vessel


def test_membrane_rul_is_preliminary_with_band():
    mh = membrane.compute_membrane_health(0.6)
    assert mh.rul is not None
    assert mh.rul.provenance.value == "preliminary"
    assert mh.rul.lower_days <= mh.rul.rul_days <= mh.rul.upper_days


# --- PdM ranking ------------------------------------------------------------


def test_ranking_orders_higher_risk_first():
    ranking = pdm.compute_ranking(0.6)
    scores = [p.rank_score for p in ranking]
    assert scores == sorted(scores, reverse=True)
    # The heavily-loaded critical HP pump outranks the lightly-used standby.
    order = [p.asset_id for p in ranking]
    assert order.index("AST-HPP-01") < order.index("AST-HPP-02")


def test_pdm_recommendations_are_preliminary_and_pending():
    recs = pdm.compute_recommendations(0.6)
    assert recs
    for rec in recs:
        assert rec.provenance.value == "preliminary"
        assert rec.approval_status.value == "pending"
        assert rec.control_boundary.control_write_enabled is False
        assert rec.rul_lower_days <= rec.rul_days <= rec.rul_upper_days


# --- Endpoints --------------------------------------------------------------

_PDM_ENDPOINTS = [
    "/api/v1/equipment/AST-HPP-01/health",
    "/api/v1/equipment/AST-HPP-01/rul",
    "/api/v1/equipment/AST-HPP-01/failure-probability",
    "/api/v1/equipment/AST-HPP-01/envelope",
    "/api/v1/equipment/AST-HPP-01/root-cause",
    "/api/v1/membrane/AST-MEMB-01/health",
    "/api/v1/maintenance/ranking",
    "/api/v1/maintenance/recommendations",
]


@pytest.mark.parametrize("path", _PDM_ENDPOINTS)
def test_endpoints_carry_boundary_and_provenance(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["control_boundary"]["control_write_enabled"] is False
    assert body["control_boundary"]["operator_approval_required"] is True
    assert body["provenance"] == "preliminary"


def test_equipment_health_returns_visible_contributions(client):
    body = client.get("/api/v1/equipment/AST-HPP-01/health").json()
    health = body["health"]
    assert 0 <= health["score"] <= 100
    assert health["contributions"]
    assert all(c["delta"] < 0 for c in health["contributions"])


def test_equipment_rul_is_preliminary_with_band(client):
    body = client.get("/api/v1/equipment/AST-HPP-01/rul").json()
    rul = body["rul"]
    assert rul["provenance"] == "preliminary"
    assert rul["lower_days"] <= rul["rul_days"] <= rul["upper_days"]


def test_equipment_failure_probability_horizons_ordered(client):
    body = client.get("/api/v1/equipment/AST-HPP-01/failure-probability").json()
    h = body["failure_probability"]["horizons"]
    assert h["24h"] <= h["7d"] <= h["30d"] <= h["90d"]


def test_root_cause_endpoint_reproduces_hpp_ranking(client):
    body = client.get("/api/v1/equipment/AST-HPP-01/root-cause").json()
    causes = [c["cause"] for c in body["root_cause"]["ranked_causes"]]
    assert causes == [
        "Membrane fouling",
        "Pump efficiency loss",
        "Feed salinity rise",
        "Valve restriction",
        "Sensor error",
    ]
    total = sum(c["probability"] for c in body["root_cause"]["ranked_causes"])
    assert total == pytest.approx(1.0, abs=1e-3)


def test_ranking_endpoint_orders_higher_risk_first(client):
    body = client.get("/api/v1/maintenance/ranking").json()
    scores = [p["rank_score"] for p in body["ranking"]]
    assert scores == sorted(scores, reverse=True)


def test_recommendations_route_pending_cards_with_write_disabled(client):
    body = client.get("/api/v1/maintenance/recommendations").json()
    assert body["recommendations"]
    assert body["cards"]
    for card in body["cards"]:
        assert card["approval_status"] == "pending"
        assert card["control_boundary"]["control_write_enabled"] is False
        assert card["control_boundary"]["operator_approval_required"] is True

    # PdM recommendations are audited and retrievable via the shared path.
    events = client.get("/api/v1/audit").json()["events"]
    assert any(e["kind"] == "pdm.recommendation.created" for e in events)
    listed = client.get("/api/v1/recommendations").json()
    assert any(r["recommendation_id"].startswith("rec-pdm-") for r in listed)


def test_recommendation_routing_is_idempotent(client):
    client.get("/api/v1/maintenance/recommendations")
    client.get("/api/v1/maintenance/recommendations")
    recs = client.get("/api/v1/recommendations").json()
    pdm_recs = [r for r in recs if r["recommendation_id"].startswith("rec-pdm-")]
    assert len(pdm_recs) == len({r["recommendation_id"] for r in pdm_recs})


def test_unknown_asset_returns_404(client):
    resp = client.get("/api/v1/equipment/AST-UNKNOWN/health")
    assert resp.status_code == 404
