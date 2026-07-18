"""The status lifecycle: only allowed transitions succeed; illegal ones raise."""

from __future__ import annotations

import pytest

from app import lifecycle
from app.audit_client import AuditClient, InMemoryAuditTransport
from app.lifecycle import IllegalTransition
from app.models import IngestStatus, UploadRecord


def _record() -> UploadRecord:
    return UploadRecord(
        tenant_id="TEN-A",
        facility_id="S3M-DESAL-01",
        filename="f.csv",
        content_type_declared="text/csv",
        content_type_detected="text/csv",
        size_bytes=10,
        sha256="0" * 64,
        uploaded_by="erin-engineer",
        uploaded_at="2026-01-01T00:00:00+00:00",
        status=IngestStatus.received,
    )


def _audit() -> AuditClient:
    return AuditClient(InMemoryAuditTransport())


def test_allowed_transition_updates_status_and_audits():
    audit = _audit()
    record = _record()
    lifecycle.record_initial(record, actor="erin-engineer", audit=audit)
    lifecycle.transition(record, IngestStatus.scanning, actor="erin-engineer", audit=audit)
    assert record.status is IngestStatus.scanning
    assert [h.status for h in record.status_history] == [
        IngestStatus.received,
        IngestStatus.scanning,
    ]
    kinds = [e["kind"] for e in audit.transport.entries]
    assert kinds == ["ingest.received", "ingest.status_transition"]


def test_illegal_transition_raises():
    audit = _audit()
    record = _record()
    # received -> parsed is not in the allowed-transition map.
    with pytest.raises(IllegalTransition):
        lifecycle.transition(record, IngestStatus.parsed, actor="erin-engineer", audit=audit)
    # The record is unchanged and no audit entry was written.
    assert record.status is IngestStatus.received
    assert audit.transport.entries == []


def test_superseded_is_reachable_from_every_non_terminal_state():
    for source, targets in lifecycle.ALLOWED_TRANSITIONS.items():
        if source is IngestStatus.superseded:
            assert targets == frozenset()
        else:
            assert IngestStatus.superseded in targets


def test_terminal_states_have_no_outgoing_transitions():
    assert lifecycle.ALLOWED_TRANSITIONS[IngestStatus.superseded] == frozenset()
