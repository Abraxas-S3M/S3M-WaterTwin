"""The single place where an :class:`UploadRecord` changes status.

Status transitions are constrained by an explicit allowed-transition map; any
transition not in the map raises :class:`IllegalTransition`. Every applied
transition (and the initial ``received`` state) appends to the record's
append-only ``status_history`` **and** writes a hash-chained audit entry via the
injected audit client. Concentrating transitions here keeps the lifecycle
auditable and impossible to bypass from route handlers.
"""

from __future__ import annotations

from .audit_client import AuditClient
from .models import IngestStatus, StatusTransition, UploadRecord

#: The only permitted status transitions. A source status maps to the set of
#: statuses it may move to. Any (from, to) pair not present here is illegal.
#: ``superseded`` is reachable from every non-terminal state (a superseding
#: upload retires an in-flight one) and is itself terminal.
ALLOWED_TRANSITIONS: dict[IngestStatus, frozenset[IngestStatus]] = {
    IngestStatus.received: frozenset(
        {IngestStatus.scanning, IngestStatus.scan_failed, IngestStatus.superseded}
    ),
    IngestStatus.scanning: frozenset(
        {IngestStatus.classified, IngestStatus.scan_failed, IngestStatus.superseded}
    ),
    IngestStatus.scan_failed: frozenset({IngestStatus.superseded}),
    IngestStatus.classified: frozenset({IngestStatus.parsing, IngestStatus.superseded}),
    IngestStatus.parsing: frozenset(
        {IngestStatus.parsed, IngestStatus.parse_failed, IngestStatus.superseded}
    ),
    IngestStatus.parse_failed: frozenset({IngestStatus.superseded}),
    IngestStatus.parsed: frozenset({IngestStatus.proposed, IngestStatus.superseded}),
    IngestStatus.proposed: frozenset({IngestStatus.submitted, IngestStatus.superseded}),
    IngestStatus.submitted: frozenset(
        {IngestStatus.approved, IngestStatus.rejected, IngestStatus.superseded}
    ),
    IngestStatus.approved: frozenset({IngestStatus.superseded}),
    IngestStatus.rejected: frozenset({IngestStatus.superseded}),
    IngestStatus.superseded: frozenset(),
}

#: The status every record starts in at intake.
INITIAL_STATUS = IngestStatus.received


class IllegalTransition(Exception):
    """Raised when a status transition is not in :data:`ALLOWED_TRANSITIONS`."""

    def __init__(self, current: IngestStatus, target: IngestStatus) -> None:
        super().__init__(
            f"illegal ingest status transition {current.value!r} -> {target.value!r}; "
            f"allowed from {current.value!r}: "
            f"{sorted(s.value for s in ALLOWED_TRANSITIONS.get(current, frozenset()))}"
        )
        self.current = current
        self.target = target


def is_allowed(current: IngestStatus, target: IngestStatus) -> bool:
    """Whether ``current -> target`` is a permitted transition."""
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def record_initial(
    record: UploadRecord,
    *,
    actor: str,
    audit: AuditClient,
    note: str | None = None,
) -> UploadRecord:
    """Record the initial ``received`` state (history entry + audit entry)."""
    if record.status is not INITIAL_STATUS:
        raise IllegalTransition(record.status, INITIAL_STATUS)
    record.status_history.append(
        StatusTransition(status=INITIAL_STATUS, actor=actor, note=note)
    )
    audit.record(
        kind="ingest.received",
        actor=actor,
        subject=str(record.ingest_id),
        payload={
            "status": INITIAL_STATUS.value,
            "tenant_id": record.tenant_id,
            "facility_id": record.facility_id,
            "filename": record.filename,
            "sha256": record.sha256,
            "size_bytes": record.size_bytes,
            "note": note,
        },
    )
    return record


def transition(
    record: UploadRecord,
    target: IngestStatus,
    *,
    actor: str,
    audit: AuditClient,
    note: str | None = None,
    error: str | None = None,
) -> UploadRecord:
    """Apply ``target`` to ``record`` (audited); raise on an illegal transition."""
    if not is_allowed(record.status, target):
        raise IllegalTransition(record.status, target)
    previous = record.status
    record.status = target
    if error is not None:
        record.error = error
    record.status_history.append(StatusTransition(status=target, actor=actor, note=note))
    audit.record(
        kind="ingest.status_transition",
        actor=actor,
        subject=str(record.ingest_id),
        payload={
            "from": previous.value,
            "to": target.value,
            "note": note,
            "error": error,
        },
    )
    return record
