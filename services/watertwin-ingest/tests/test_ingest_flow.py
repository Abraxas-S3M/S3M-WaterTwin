"""End-to-end tests for the advisory file-intake flow.

Exercise classify -> preview -> submit -> approve through the in-memory config
lifecycle client, plus the safety invariants: nothing writes to OT, separation
of duties is enforced server-side, and original-file download is admin-only.
"""

from __future__ import annotations

import pytest
from app.main import app
from fastapi.testclient import TestClient

DEMO_INP = """\
[TITLE]
Demo RO intake network

[JUNCTIONS]
;ID   Elev   Demand
J1    100    0
J2    98     5

[RESERVOIRS]
R1    120

[PIPES]
P1   J1    J2    100    300  100

[PUMPS]
PMP1  R1   J1   HEAD C1
PMP2  J1   J2   HEAD C2
BADPUMP

[VALVES]
V1   J2   J1   300  PRV  50  0

[END]
"""


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        yield c
        c.post("/api/v1/reset")


def _classify(client: TestClient, actor: str = "erin-engineer") -> dict:
    resp = client.post(
        "/api/v1/ingest/classify",
        headers={"X-Actor": actor, "X-Roles": "engineer"},
        json={"filename": "demo.inp", "size_bytes": len(DEMO_INP), "content": DEMO_INP},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_status_reports_availability_and_boundary(client: TestClient):
    body = client.get("/api/v1/ingest/status").json()
    assert body["available"] is True
    assert body["control_boundary"]["control_write_enabled"] is False
    assert body["accepted_types"][0]["extension"] == ".inp"


def test_status_unavailable_for_disabled_profile(client: TestClient, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "edge")
    body = client.get("/api/v1/ingest/status").json()
    assert body["available"] is False


def test_classify_sniffs_epanet(client: TestClient):
    body = _classify(client)
    assert body["suggested_class"] == "epanet_inp"
    assert body["confidence"] > 0.5
    assert len(body["sha256"]) == 64


def test_preview_reports_counts_and_unparsed_with_reasons(client: TestClient):
    upload = _classify(client)
    preview = client.get(f"/api/v1/ingest/uploads/{upload['upload_id']}/preview").json()
    assert preview["status"] == "ready"
    sections = {c["entity"]: c for c in preview["entity_counts"]}
    assert sections["pumps"]["found"] == 2
    assert sections["valves"]["found"] == 1
    # The malformed pump line is captured with a line number + plain reason.
    assert preview["unparsed"], "expected the BADPUMP line to be reported"
    reason = preview["unparsed"][0]["reason"].lower()
    assert "pump" in reason and "parse failed" not in reason
    # Diff is grouped under the asset-hierarchy panel and is safety-relevant.
    assert preview["diff"][0]["panel"] == "asset-hierarchy"
    assert all(row["safety_relevant"] for row in preview["diff"][0]["rows"])


def test_submit_creates_only_accepted_drafts_and_flags_sod(client: TestClient):
    upload = _classify(client)
    # Accept only PMP1's rows.
    decisions = [
        {"row_id": "PMP1:asset_type", "accepted": True},
        {"row_id": "PMP1:name", "accepted": True},
        {"row_id": "PMP2:asset_type", "accepted": False, "reject_reason": "duplicate"},
    ]
    resp = client.post(
        "/api/v1/ingest/submit",
        headers={"X-Actor": "erin-engineer", "X-Roles": "engineer"},
        json={"upload_id": upload["upload_id"], "actor": "erin-engineer", "decisions": decisions},
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    created_ids = {v["config_id"] for v in result["created_versions"]}
    assert created_ids == {"PMP1"}
    assert all(v["status"] == "submitted" for v in result["created_versions"])
    # Asset hierarchy is safety-relevant -> a separate approver is required.
    assert result["requires_separate_approver"] is True
    assert result["self_approval_blocked"] is True
    assert result["blocked_entities"] == ["asset"]
    assert result["control_boundary"]["control_write_enabled"] is False


def test_separation_of_duties_blocks_self_approval(client: TestClient):
    upload = _classify(client, actor="erin-engineer")
    client.post(
        "/api/v1/ingest/submit",
        headers={"X-Actor": "erin-engineer", "X-Roles": "engineer"},
        json={
            "upload_id": upload["upload_id"],
            "actor": "erin-engineer",
            "decisions": [{"row_id": "PMP1:name", "accepted": True}],
        },
    )
    # Same person cannot approve their own safety-relevant submission.
    same = client.post(
        f"/api/v1/ingest/uploads/{upload['upload_id']}/approve",
        headers={"X-Actor": "erin-engineer", "X-Roles": "engineer"},
    )
    assert same.status_code == 403
    # A different approver may.
    other = client.post(
        f"/api/v1/ingest/uploads/{upload['upload_id']}/approve",
        headers={"X-Actor": "ada-admin", "X-Roles": "admin"},
    )
    assert other.status_code == 200, other.text
    assert other.json()["control_boundary"]["control_write_enabled"] is False


def test_history_and_admin_only_original_download(client: TestClient):
    upload = _classify(client)
    history = client.get("/api/v1/ingest/history").json()
    assert any(i["upload_id"] == upload["upload_id"] for i in history["items"])

    # Non-admin cannot download the original file.
    forbidden = client.get(
        f"/api/v1/ingest/uploads/{upload['upload_id']}/original",
        headers={"X-Actor": "sam-operator", "X-Roles": "operator"},
    )
    assert forbidden.status_code == 403
    # Admin can.
    ok = client.get(
        f"/api/v1/ingest/uploads/{upload['upload_id']}/original",
        headers={"X-Actor": "ada-admin", "X-Roles": "admin"},
    )
    assert ok.status_code == 200
    assert "[PUMPS]" in ok.text


def test_onboarding_reports_no_assets_initially(client: TestClient):
    body = client.get("/api/v1/ingest/onboarding").json()
    assert body["has_assets"] is False
    keys = {c["key"] for c in body["checklist"]}
    assert keys == {"network_model", "equipment_specs", "tag_mapping", "documents"}
