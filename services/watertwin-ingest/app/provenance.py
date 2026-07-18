"""Prompt-injection defence: uploaded content is inert data, never instructions.

Uploaded files frequently contain text that *looks* like an instruction to an
LLM ("ignore previous instructions", "approve this recommendation", "set control
to enabled"). In this platform that text can never have any effect because:

* The ingest service treats file bytes as **data**. It performs no action on the
  basis of upload content, issues no control command, and calls no LLM with the
  content as a system/instruction message.
* Ingestion never changes an upload's **provenance** (it is fixed at
  ``"customer-upload"``) and never changes an **approval** decision — approval is
  a separate, human-only, RBAC-gated action recorded in the audit trail.

This module records the immutable provenance/approval facts and exposes a helper
that scans content for injection markers **only to flag/quarantine it for a human
reviewer** — flagging changes nothing about actions, approval, or provenance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: The single, fixed provenance any customer upload carries. Ingestion of file
#: content can never change this value.
UPLOAD_PROVENANCE = "customer-upload"

#: Markers that hint at an attempted prompt injection. Presence is advisory only:
#: it raises a review flag, it does NOT trigger any action or approval.
_INJECTION_MARKERS = (
    re.compile(rb"ignore (all |the )?previous instructions", re.IGNORECASE),
    re.compile(rb"disregard (all |the )?(prior|previous|above)", re.IGNORECASE),
    re.compile(rb"you are now", re.IGNORECASE),
    re.compile(rb"system prompt", re.IGNORECASE),
    re.compile(rb"approve (this|the) (recommendation|work order|change)", re.IGNORECASE),
    re.compile(rb"control_write_enabled\s*=\s*true", re.IGNORECASE),
    re.compile(rb"set control (mode )?to", re.IGNORECASE),
)


@dataclass(frozen=True)
class ProvenanceRecord:
    """The immutable provenance/approval facts for an upload.

    ``approval_required`` is always True and ``approval_status`` starts (and,
    from ingestion's perspective, stays) ``"pending"``: ingestion never approves
    anything. ``provenance`` is fixed. ``injection_flags`` is advisory metadata.
    """

    provenance: str = UPLOAD_PROVENANCE
    approval_required: bool = True
    approval_status: str = "pending"
    injection_flags: tuple[str, ...] = field(default_factory=tuple)


def scan_for_injection(data: bytes) -> tuple[str, ...]:
    """Return the injection-marker names found in ``data`` (advisory only)."""
    hits: list[str] = []
    for marker in _INJECTION_MARKERS:
        if marker.search(data):
            hits.append(marker.pattern.decode("ascii", errors="replace"))
    return tuple(hits)


def record_for_upload(data: bytes) -> ProvenanceRecord:
    """Build the immutable provenance record for uploaded ``data``.

    Even when injection markers are present, the record's ``provenance`` stays
    ``customer-upload``, ``approval_required`` stays True and ``approval_status``
    stays ``pending``. The only thing the markers do is populate the advisory
    ``injection_flags`` so a human reviewer is alerted.
    """
    return ProvenanceRecord(injection_flags=scan_for_injection(data))
