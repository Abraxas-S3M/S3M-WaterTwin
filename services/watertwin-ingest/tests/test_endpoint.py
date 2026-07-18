"""Endpoint tests for POST /api/v1/ingest/uploads/{id}/analysis."""

from __future__ import annotations

from fastapi.testclient import TestClient

import app.analysis as analysis
from app.main import app

from .fake_s3m import FakeAnalysisClient, pump_curve_outputs, pump_curve_parse_result


def _payload():
    return {
        "parse_result": pump_curve_parse_result().model_dump(mode="json"),
        "approved_documents": [{"document_id": "DS-P003"}],
        "requested_by": "operator-jane",
    }


def _isolate(monkeypatch):
    """Point the endpoint at a fresh fake client + fresh cache/audit singletons."""
    client = FakeAnalysisClient(pump_curve_outputs())
    fresh_audit = analysis.AuditChain()
    monkeypatch.setattr(analysis, "get_analysis_client", lambda: client)
    monkeypatch.setattr(analysis, "get_audit_chain", lambda: fresh_audit)
    monkeypatch.setattr(analysis, "_cache", analysis.AnalysisCache())
    return client


def test_analysis_endpoint_returns_unaccepted_cited_changes(monkeypatch):
    _isolate(monkeypatch)
    http = TestClient(app)
    resp = http.post("/api/v1/ingest/uploads/ING-001/analysis", json=_payload())

    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["anomalies"]
    assert data["proposed_changes"]
    for change in data["proposed_changes"]:
        assert change["ai_suggested"] is True
        assert change["accepted"] is False


def test_analysis_endpoint_is_idempotent(monkeypatch):
    client = _isolate(monkeypatch)
    http = TestClient(app)

    http.post("/api/v1/ingest/uploads/ING-001/analysis", json=_payload())
    http.post("/api/v1/ingest/uploads/ING-001/analysis", json=_payload())

    assert client.calls == 1


def test_analysis_endpoint_rejects_mismatched_upload_id(monkeypatch):
    _isolate(monkeypatch)
    http = TestClient(app)
    resp = http.post("/api/v1/ingest/uploads/OTHER/analysis", json=_payload())
    assert resp.status_code == 400


def test_health_reports_read_only_boundary():
    http = TestClient(app)
    resp = http.get("/api/v1/ingest/health")
    assert resp.status_code == 200
    boundary = resp.json()["control_boundary"]
    assert boundary["control_mode"] == "advisory"
    assert boundary["operator_approval_required"] is True
    assert boundary["control_write_enabled"] is False
