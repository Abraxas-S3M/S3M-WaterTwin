"""ADR-0014 T12 — Repudiation.

Control: a tamper-evident, hash-chained audit trail records the full lifecycle
from upload through approval. The chain is verifiable and any alteration of a
past event (its payload, actor, or order) is detected.
"""

from __future__ import annotations

from app.audit import verify_chain
from app.service import IngestService


def _upload_and_approve():
    svc = IngestService(profile="standard")
    record = svc.upload(
        tenant_id="TEN-A",
        uploaded_by="alice",
        filename="lab.csv",
        data=b"analyte,value\nturbidity,0.3\n",
        parser="csv",
    )
    svc.approve(
        caller_tenant="TEN-A",
        upload_id=record.upload_id,
        approver="eng-carol",
        decision="approved",
    )
    return svc, record


def test_full_chain_from_upload_through_approval():
    svc, record = _upload_and_approve()
    trail = svc.audit_trail(caller_tenant="TEN-A", upload_id=record.upload_id)
    kinds = [e["kind"] for e in trail]
    # The complete lifecycle is recorded in order.
    assert kinds == [
        "upload.received",
        "upload.scanned",
        "upload.parsed",
        "upload.approval",
    ]
    # The approver and uploader are both attributable (non-repudiable).
    assert trail[0]["actor"] == "alice"
    assert trail[-1]["actor"] == "eng-carol"
    assert trail[-1]["payload"]["decision"] == "approved"
    # Approval is not a control write.
    assert trail[-1]["payload"]["control_write_enabled"] is False


def test_chain_verifies_and_is_hash_linked():
    svc, _ = _upload_and_approve()
    result = svc.verify_audit()
    assert result["ok"] is True
    assert result["count"] >= 4


def test_tampering_with_a_past_event_is_detected():
    svc, record = _upload_and_approve()
    # An attacker edits the stored payload of the approval event to repudiate it.
    events = svc.audit.events()
    events[-1]["payload"]["decision"] = "rejected"
    verdict = verify_chain(events)
    assert verdict["ok"] is False
    assert verdict["reason"].startswith("hash mismatch")


def test_deleting_a_past_event_breaks_the_chain():
    svc, _ = _upload_and_approve()
    events = svc.audit.events()
    tampered = events[:1] + events[2:]  # drop the scan event
    verdict = verify_chain(tampered)
    assert verdict["ok"] is False


def test_content_deletion_leaves_audit_intact():
    svc, record = _upload_and_approve()
    svc.delete_content(
        caller_tenant="TEN-A", upload_id=record.upload_id, actor="alice"
    )
    # Deletion appends a 'deleted' event; the chain still verifies and the
    # earlier events (upload/approval) still exist (audit survives deletion).
    assert svc.verify_audit()["ok"] is True
    kinds = [e["kind"] for e in svc.audit_trail(caller_tenant="TEN-A", upload_id=record.upload_id)]
    assert "upload.deleted" in kinds
    assert "upload.received" in kinds
