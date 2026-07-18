"""Approval proposals emitted by the bulk-import parsers.

Every parser produces an :class:`ImportProposal` instead of committing data.
The proposal is a decision-support artifact: it describes what *would* be
imported if a human operator approves it. It carries the read-only control
boundary and states explicitly that approving an import does **not** promote any
analytic from ``preliminary`` to ``calibrated``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from canonical_water_model import ApprovalStatus, ControlBoundary, now_iso

PROPOSAL_TIMESERIES_IMPORT = "timeseries_import"
PROPOSAL_GIS_LAYER_IMPORT = "gis_layer_import"


@dataclass(frozen=True)
class ImportProposal:
    """A human-approval proposal to import a staged artifact.

    The proposal never triggers the import itself. ``requires_operator_approval``
    is always ``True`` and ``promotes_to_calibrated`` is always ``False``: an
    import moves raw customer data into staging for review, it does not validate
    or calibrate anything.
    """

    proposal_id: str
    kind: str
    dataset_id: str
    provenance: str
    staged_artifact_id: str
    record_count: int
    summary: dict[str, Any] = field(default_factory=dict)
    requires_operator_approval: bool = True
    promotes_to_calibrated: bool = False
    status: ApprovalStatus = ApprovalStatus.pending
    control_boundary: ControlBoundary = field(default_factory=ControlBoundary)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "kind": self.kind,
            "dataset_id": self.dataset_id,
            "provenance": self.provenance,
            "staged_artifact_id": self.staged_artifact_id,
            "record_count": self.record_count,
            "summary": self.summary,
            "requires_operator_approval": self.requires_operator_approval,
            "promotes_to_calibrated": self.promotes_to_calibrated,
            "status": self.status.value,
            "control_boundary": self.control_boundary.model_dump(),
            "created_at": self.created_at,
        }
