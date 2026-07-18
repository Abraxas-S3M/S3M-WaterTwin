"""Service-level smoke tests for watertwin-ingest.

The exhaustive, threat-model-mapped controls are proven in ``security/tests/``;
these are fast local sanity checks that the app wires together and the HTTP
surface behaves.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.service import IngestService


def test_health_reports_read_only_posture():
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["control_mode"] == "advisory"
    assert body["operator_approval_required"] is True
    assert body["control_write_enabled"] is False
    assert body["safety_invariant_intact"] is True


def test_capabilities_expose_nav_and_posture():
    caps = IngestService(profile="standard").capabilities()
    assert caps["ingestion_enabled"] is True
    assert caps["nav"]["ingestion"]["visible"] is True
    assert caps["control_boundary"]["control_write_enabled"] is False
    assert caps["optional"] is True


def test_upload_parse_and_read_roundtrip():
    svc = IngestService(profile="standard")
    record = svc.upload(
        tenant_id="TEN-A",
        uploaded_by="alice",
        filename="lab.csv",
        data=b"analyte,value\nturbidity,0.3\n",
        parser="csv",
    )
    assert record.provenance == "customer-upload"
    assert record.approval_status == "pending"
    listed = svc.list_uploads(caller_tenant="TEN-A")
    assert len(listed) == 1
    content = svc.get_content(caller_tenant="TEN-A", upload_id=record.upload_id)
    assert content == b"analyte,value\nturbidity,0.3\n"
    assert svc.verify_audit()["ok"] is True
