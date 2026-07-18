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
"""Provenance labels and CRS constants for bulk file imports.

These labels are deliberately **distinct** from the canonical
:class:`canonical_water_model.DataProvenance` values. A file that a customer
hands us is not, by the mere act of import, ``measured`` platform data and is
never ``calibrated``. It is *customer-asserted* until the documented validation
process (with a named engineer's sign-off) says otherwise. Keeping these as their
own label set makes it impossible for an import to accidentally stamp data with a
canonical provenance that implies validation.
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
from enum import Enum

#: Platform coordinate reference system. All staged geometry is reprojected to
#: this CRS (WGS84 lon/lat, RFC 7946), matching ``network_twin`` geo-referencing.
PLATFORM_CRS = "EPSG:4326"


class IngestProvenance(str, Enum):
    """Provenance for data admitted through the bulk-import staging path."""

    #: Historian time-series a customer exported and measured on their plant.
    customer_measured = "customer_measured"
    #: Geospatial layers a customer supplied (network geometry, asset overlays).
    customer_supplied = "customer_supplied"
