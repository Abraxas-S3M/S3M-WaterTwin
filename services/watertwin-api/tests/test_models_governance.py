"""Tests for model governance (D1/D2) + regulatory compliance (A1 config store).

Fast and dependency-free (no live hydraulic-sim): they lock the governance
registry shape, the configurable compliance-limit exceedance detection, and that
the printable regulatory report renders with provenance + the standard
disclaimer + the mandatory read-only boundary footer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from canonical_water_model import ComplianceLimit, LimitBound

from app import compliance
from app import model_registry
from app.config_store import ConfigStore
from app.main import app
from app.reports import build_compliance_report


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        yield c


# --- Registry shape (D1/D2 governance) -------------------------------------


def test_registry_entry_shape():
    registry = model_registry.build_registry(0.0)
    assert registry
    ids = {entry.model_id for entry in registry}
    # The canonical + derived intelligence models are all registered.
    assert {"water-quality-ro", "membrane-health", "predictive-maintenance"} <= ids

    for entry in registry:
        # Governance identity + version + track.
        assert entry.model_id and entry.name and entry.version
        assert entry.track in {"D1", "D2"}
        # Spec: inputs/outputs/method are present.
        assert entry.spec.method
        assert entry.spec.outputs
        # Drift status is a known disposition.
        assert entry.drift_status.value in {"stable", "watch", "drifting", "unknown"}
        # Advisory + read-only: never presented as validated/measured.
        assert entry.provenance.value != "measured"
        assert entry.control_boundary.control_write_enabled is False
        # Metrics carry a value and (when a baseline exists) a drift figure.
        for metric in entry.current_metrics:
            assert metric.value is not None


def test_registry_endpoint_shape(client):
    body = client.get("/api/v1/models").json()
    assert body["count"] == len(body["models"])
    assert body["control_boundary"]["control_write_enabled"] is False
    entry = body["models"][0]
    for key in ("model_id", "name", "version", "track", "spec", "current_metrics", "drift_status"):
        assert key in entry
    assert "inputs" in entry["spec"] and "outputs" in entry["spec"] and "method" in entry["spec"]


def test_registry_reports_drift_as_operating_point_moves_off_baseline():
    clean = {e.model_id: e for e in model_registry.build_registry(0.0)}
    fouled = {e.model_id: e for e in model_registry.build_registry(0.85)}

    wq_clean = clean["water-quality-ro"]
    wq_fouled = fouled["water-quality-ro"]
    # At the registered baseline there is no drift; off-baseline it drifts.
    assert wq_clean.drift_status.value == "stable"
    assert wq_fouled.drift_status.value in {"watch", "drifting"}
    # A metric exposes its baseline reference + relative drift.
    salt = next(m for m in wq_fouled.current_metrics if m.name == "normalized_salt_passage")
    assert salt.reference is not None
    assert salt.drift_pct is not None and salt.drift_pct != 0.0


def test_model_detail_unknown_returns_404(client):
    assert client.get("/api/v1/models/does-not-exist").status_code == 404


# --- Exceedance detection against configured limits (A1 config store) -------


def test_check_limit_max_and_min_bounds():
    max_limit = ComplianceLimit(
        parameter="turbidity_ntu", display_name="Turbidity", unit="NTU", limit=0.3
    )
    assert compliance.check_limit(max_limit, 0.2).within_limit is True
    over = compliance.check_limit(max_limit, 0.6)
    assert over.within_limit is False
    assert over.exceedance_pct == pytest.approx(100.0, abs=0.1)

    min_limit = ComplianceLimit(
        parameter="free_chlorine_mg_l",
        display_name="Chlorine residual",
        unit="mg/L",
        limit=0.2,
        bound=LimitBound.min,
    )
    assert compliance.check_limit(min_limit, 0.5).within_limit is True
    under = compliance.check_limit(min_limit, 0.1)
    assert under.within_limit is False
    assert under.exceedance_pct == pytest.approx(50.0, abs=0.1)


def test_configured_limits_drive_exceedance_detection():
    store = ConfigStore(load_env=False)
    # A deliberately strict, operator-configured limit drives an exceedance.
    store.set_limit(
        ComplianceLimit(
            parameter="conductivity_us_cm",
            display_name="Conductivity",
            unit="µS/cm",
            limit=1.0,
            bound=LimitBound.max,
            stage="finished",
            basis="test-strict",
        )
    )
    evaluation = compliance.evaluate(store.limits(), fouling=0.5)
    flagged = {e.parameter for e in evaluation.exceedances}
    assert "conductivity_us_cm" in flagged
    assert evaluation.compliant is False

    # Relaxing that same limit removes the exceedance -> the store is configurable.
    store.set_limit(
        ComplianceLimit(
            parameter="conductivity_us_cm",
            display_name="Conductivity",
            unit="µS/cm",
            limit=1_000_000.0,
            bound=LimitBound.max,
            stage="finished",
            basis="test-relaxed",
        )
    )
    relaxed = compliance.evaluate(store.limits(), fouling=0.5)
    assert "conductivity_us_cm" not in {e.parameter for e in relaxed.exceedances}


def test_compliance_status_endpoint_flags_exceedances(client):
    body = client.get("/api/v1/compliance/status?fouling=0.95").json()
    assert body["control_boundary"]["control_write_enabled"] is False
    assert body["provenance"] == "synthetic"
    assert body["compliant"] is False
    # Every exceedance is a failed check that carries its regulatory basis.
    assert body["exceedances"]
    for ex in body["exceedances"]:
        assert ex["within_limit"] is False
        assert ex["basis"]


def test_compliance_limits_endpoint_lists_configured_parameters(client):
    body = client.get("/api/v1/compliance/limits").json()
    params = {limit["parameter"] for limit in body["limits"]}
    assert {"turbidity_ntu", "conductivity_us_cm", "free_chlorine_mg_l"} <= params


# --- Report renders ---------------------------------------------------------


def test_build_compliance_report_renders_with_provenance_and_disclaimer():
    store = ConfigStore(load_env=False)
    limits = store.limits()
    evaluation = compliance.evaluate(limits, fouling=0.95)
    doc = build_compliance_report(evaluation, limits)

    assert "# Regulatory Compliance Summary" in doc
    assert "Configured limits (A1 config store)" in doc
    assert "Exceedances" in doc
    # Provenance carried through + configured basis surfaced.
    assert "Provenance" in doc
    assert "synthetic" in doc
    assert "WHO GDWQ" in doc
    # Mandatory read-only boundary footer + standard disclaimer.
    assert "Control boundary" in doc
    assert "control_write_enabled: `false`" in doc
    assert "advisory and preliminary" in doc


def test_compliance_report_endpoint_is_downloadable_and_audited(client):
    resp = client.post("/api/v1/reports/compliance?fouling=0.95")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    assert "Regulatory Compliance Summary" in resp.text

    events = client.get("/api/v1/audit").json()["events"]
    assert any(e["kind"] == "report.compliance.generated" for e in events)
