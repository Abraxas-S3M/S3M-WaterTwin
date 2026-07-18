"""Upload happy path, pre-storage size cap, content-type sniff, and audit."""

from __future__ import annotations

import hashlib

from helpers import upload


def _engineer(client):
    return client.token("erin-engineer", ["engineer"], "TEN-A")


def test_upload_happy_path_returns_record_with_correct_sha256(client):
    content = b"timestamp,tag,value\n2026-01-01T00:00:00Z,PU-1.flow,42.0\n"
    resp = upload(
        client,
        filename="readings.csv",
        content=content,
        content_type="text/csv",
        declared_class="sensor_export",
        headers=_engineer(client),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert body["size_bytes"] == len(content)
    # tenant is bound from the token, never the body.
    assert body["tenant_id"] == "TEN-A"
    assert body["uploaded_by"] == "erin-engineer"
    # The lifecycle moved received -> scanning -> classified; the history is the
    # append-only proof.
    statuses = [h["status"] for h in body["status_history"]]
    assert statuses[0] == "received"
    assert "scanning" in statuses
    assert body["status"] == "classified"


def test_upload_tenant_id_is_bound_from_token_not_body(client):
    # Even if a facility is supplied, tenant always comes from the token.
    resp = upload(
        client,
        filename="a.csv",
        content=b"x,y\n1,2\n",
        content_type="text/csv",
        headers=client.token("ada-admin", ["admin"], "TEN-Z"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["tenant_id"] == "TEN-Z"


def test_oversize_is_rejected_pre_storage(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "DEFAULT_SIZE_CAP_BYTES", 8, raising=False)
    monkeypatch.setenv("INGEST_CLASS_SIZE_CAPS", '{"generic": 8}')
    resp = upload(
        client,
        filename="big.csv",
        content=b"way-too-large-body-well-over-eight-bytes",
        content_type="text/csv",
        declared_class="generic",
        headers=_engineer(client),
    )
    assert resp.status_code == 413, resp.text
    # Nothing was stored: the tenant has no records.
    listing = client.get("/api/v1/ingest/uploads", headers=_engineer(client)).json()
    assert listing["total"] == 0


def test_extension_magic_byte_mismatch_is_rejected(client):
    # A .csv whose bytes are actually a PDF is a content-type contradiction.
    resp = upload(
        client,
        filename="data.csv",
        content=b"%PDF-1.7\n%stuff\n",
        content_type="text/csv",
        headers=_engineer(client),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "content_type_mismatch"


def test_audit_entry_written_for_upload_and_soft_delete(client):
    from app.main import get_audit_client

    resp = upload(
        client,
        filename="lab.csv",
        content=b"analyte,result\nboron,0.4\n",
        content_type="text/csv",
        headers=_engineer(client),
    )
    assert resp.status_code == 200, resp.text
    ingest_id = resp.json()["ingest_id"]

    kinds = [e["kind"] for e in get_audit_client().transport.entries]
    assert "ingest.received" in kinds
    assert "ingest.status_transition" in kinds

    # Soft delete retains the audit trail and appends a delete entry.
    delete = client.delete(f"/api/v1/ingest/uploads/{ingest_id}", headers=_engineer(client))
    assert delete.status_code == 200, delete.text
    assert delete.json()["audit_retained"] is True

    entries = get_audit_client().transport.entries
    delete_entries = [e for e in entries if e["kind"] == "ingest.deleted"]
    assert len(delete_entries) == 1
    assert delete_entries[0]["subject"] == ingest_id

    # The deleted record is hidden from reads but the id is gone (404), audit kept.
    assert client.get(
        f"/api/v1/ingest/uploads/{ingest_id}", headers=_engineer(client)
    ).status_code == 404
