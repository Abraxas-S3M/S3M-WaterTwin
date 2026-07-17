"""Tests for the Water Quality Intelligence engine + API endpoints.

These are fast and dependency-free (no live hydraulic-sim): they exercise the
synthetic generator, the deterministic WQ engine, the six read-only endpoints,
and the recommendation + audit routing for alerts.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import water_quality as wq
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        yield c


# --- Engine -----------------------------------------------------------------


def test_snapshot_emits_priority_variables_at_all_sampling_points():
    snap = wq.compute_snapshot(0.0)
    assert len(snap.samples) == 20  # SP-01..SP-20
    point_ids = {s.sampling_point_id for s in snap.samples}
    assert point_ids == {f"SP-{i:02d}" for i in range(1, 21)}
    # Intake carries the full priority-variable suite; all synthetic.
    intake = next(s for s in snap.samples if s.sampling_point_id == "SP-01")
    assert intake.provenance.value == "synthetic"
    for key in ("turbidity_ntu", "sdi", "boron_mg_l", "silica_mg_l", "sulfate_mg_l", "atp_pg_ml"):
        assert key in intake.measurements


def test_salt_passage_plus_rejection_is_one():
    snap = wq.compute_snapshot(0.2)
    assert snap.salt_passage + snap.salt_rejection == pytest.approx(1.0, abs=1e-9)


def test_fouling_tick_raises_normalized_dp_and_salt_passage_and_fires_alert():
    base = wq.compute_snapshot(0.0)
    fouled = wq.compute_snapshot(0.85)
    assert fouled.normalized_dp_bar > base.normalized_dp_bar
    assert fouled.salt_passage > base.salt_passage
    assert fouled.normalized_salt_passage > base.normalized_salt_passage
    assert len(fouled.alerts) >= 1
    # The fouling scenario surfaces a pretreatment-breakthrough alert.
    assert any(a.code == "WQ-PRETREATMENT-BREAKTHROUGH" for a in fouled.alerts)


def test_forecasts_are_preliminary_and_bounded():
    snap = wq.compute_snapshot(0.3)
    assert snap.forecasts
    for f in snap.forecasts:
        assert f.provenance.value == "preliminary"
        assert f.lower <= f.predicted_value <= f.upper
        assert 0.0 <= f.confidence <= 1.0
    horizons = {f.horizon for f in snap.forecasts}
    assert {"1h", "shift", "24h"}.issubset(horizons)


def test_contaminant_matrix_removal_is_positive_for_salts():
    snap = wq.compute_snapshot(0.0)
    by_name = {r.contaminant: r for r in snap.contaminant_matrix}
    assert by_name["Boron"].removal_pct is not None
    assert by_name["TDS"].removal_pct > 90.0
    assert by_name["Sulfate"].removal_pct > 90.0


# --- Endpoints --------------------------------------------------------------

_WQ_ENDPOINTS = [
    "/api/v1/water-quality/status",
    "/api/v1/water-quality/contaminant-matrix",
    "/api/v1/water-quality/removal",
    "/api/v1/water-quality/scaling",
    "/api/v1/water-quality/forecast",
    "/api/v1/water-quality/alerts",
]


@pytest.mark.parametrize("path", _WQ_ENDPOINTS)
def test_endpoints_carry_boundary_and_provenance(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["control_boundary"]["control_write_enabled"] is False
    assert body["control_boundary"]["operator_approval_required"] is True
    assert body["provenance"] in {"synthetic", "preliminary"}


def test_status_reports_compliance_and_summary(client):
    body = client.get("/api/v1/water-quality/status").json()
    assert body["stage_status"]
    assert "salt_passage" in body["summary"]
    for stage in body["stage_status"]:
        assert "compliance" in stage


def test_scaling_endpoint_lists_expected_compounds(client):
    body = client.get("/api/v1/water-quality/scaling").json()
    compounds = {r["compound"] for r in body["scaling"]}
    assert {"CaCO3", "CaSO4", "BaSO4", "SrSO4", "SiO2"}.issubset(compounds)


def test_alerts_route_pending_recommendations_with_write_disabled(client):
    body = client.get("/api/v1/water-quality/alerts?fouling=0.85").json()
    assert body["alerts"]
    assert body["recommendations"]
    for rec in body["recommendations"]:
        assert rec["approval_status"] == "pending"
        assert rec["control_boundary"]["control_write_enabled"] is False
        assert rec["control_boundary"]["operator_approval_required"] is True

    # Alerts are audited and the recommendations are retrievable.
    events = client.get("/api/v1/audit").json()["events"]
    assert any(e["kind"] == "wq.alert.created" for e in events)
    listed = client.get("/api/v1/recommendations").json()
    assert any(r["recommendation_id"].startswith("rec-wq-") for r in listed)


def test_alerts_routing_is_idempotent(client):
    first = client.get("/api/v1/water-quality/alerts?fouling=0.85").json()
    client.get("/api/v1/water-quality/alerts?fouling=0.85")
    recs = client.get("/api/v1/recommendations").json()
    wq_recs = [r for r in recs if r["recommendation_id"].startswith("rec-wq-")]
    # No duplicates despite repeated polling.
    assert len(wq_recs) == len({r["recommendation_id"] for r in wq_recs})
    assert len(wq_recs) == len(
        {a["code"] for a in first["alerts"]}
    )
