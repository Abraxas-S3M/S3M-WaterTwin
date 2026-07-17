"""The advisory event envelope carried on the bus.

Every message published to the bus is an :class:`EventEnvelope`: a small,
self-describing, JSON-serializable record that stamps the read-only control
boundary (``control_write_enabled = False``) onto the wire so a consumer can
always see that the event is advisory. The envelope carries a notification
*payload* only -- it is deliberately incapable of expressing a control command,
and its subject is validated by :func:`~watertwin_events.subjects.assert_advisory_subject`
at construction time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from .subjects import assert_advisory_subject, event_type_of


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class EventControlBoundary(BaseModel):
    """The read-only control boundary stamped on every event (advisory only)."""

    control_mode: str = "advisory"
    operator_approval_required: bool = True
    control_write_enabled: bool = False


class EventEnvelope(BaseModel):
    """A single advisory service event.

    ``subject`` is a guarded ``watertwin.events.*`` subject; ``payload`` is a
    plain notification body (never a control instruction). The envelope always
    reports ``advisory = True`` and a control boundary with control writes
    disabled.
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    subject: str
    event_type: str = ""
    source: str = "watertwin"
    occurred_at: str = Field(default_factory=_now_iso)
    facility_id: str | None = None
    train_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    advisory: bool = True
    control_boundary: EventControlBoundary = Field(default_factory=EventControlBoundary)

    def to_bytes(self) -> bytes:
        """Serialize the envelope to UTF-8 JSON bytes for the wire."""
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes | str) -> EventEnvelope:
        """Parse an envelope back from wire bytes/str."""
        return cls.model_validate_json(data)


def build_envelope(
    subject: str,
    payload: dict[str, Any] | None = None,
    *,
    source: str = "watertwin",
    facility_id: str | None = None,
    train_id: str | None = None,
) -> EventEnvelope:
    """Build a guarded, advisory :class:`EventEnvelope` for ``subject``.

    The subject is validated by
    :func:`~watertwin_events.subjects.assert_advisory_subject`, so a control
    command can never be wrapped in an envelope.
    """
    assert_advisory_subject(subject)
    return EventEnvelope(
        subject=subject,
        event_type=event_type_of(subject),
        source=source,
        facility_id=facility_id,
        train_id=train_id,
        payload=payload or {},
    )
