"""Build a field-level :class:`ChangeProposal` from the reconciler output.

Each :class:`ProposedChange` has exactly the shape from ADR-0014 §6.2:

    entity, record_id, field, current_value, proposed_value, source_ref,
    provenance, match_confidence, conflict, ai_suggested, ai_confidence,
    ai_rationale, accepted

Two safety-critical invariants are enforced structurally here:

* ``provenance`` for every EPANET-derived value is ``customer_supplied``.
* ``accepted`` **always** defaults to ``False``. There is no code path in this
  module (or anywhere server-side) that sets ``accepted=True`` — accepting a
  change requires an explicit, per-field request from a human, handled outside
  this build step. The proposal is advisory only; nothing here is applied.
"""

from __future__ import annotations

from typing import Any

from canonical_water_model import ControlBoundary, now_iso
from pydantic import BaseModel, Field

from .parsers import ParseResult
from .reconciler import FieldClassification, ReconcileResult

#: Provenance stamped on every value derived from a customer-uploaded file.
CUSTOMER_SUPPLIED = "customer_supplied"


class ProposedChange(BaseModel):
    """One proposed field change for human review (ADR-0014 §6.2 shape)."""

    entity: str
    record_id: str
    field: str
    current_value: Any = None
    proposed_value: Any = None
    source_ref: str
    provenance: str = CUSTOMER_SUPPLIED
    match_confidence: float
    conflict: bool = False
    ai_suggested: bool = False
    ai_confidence: float | None = None
    ai_rationale: str | None = None
    #: ALWAYS False here. Accepting a change is a separate, explicit, per-field
    #: human action; there is no server-side path that flips this True.
    accepted: bool = False


class ProposalEntitySummary(BaseModel):
    """Per-type roll-up of the entities covered by the proposal."""

    entity_type: str
    total: int = 0
    matched: int = 0
    new: int = 0
    conflicts: int = 0


class ChangeProposal(BaseModel):
    """An advisory, human-reviewable set of proposed canonical changes.

    A :class:`ChangeProposal` is never applied automatically: it is decision
    support. The read-only :class:`ControlBoundary` is stamped on it to make the
    advisory posture explicit, exactly as elsewhere on the platform.
    """

    upload_id: str | None = None
    source_file: str
    parser: str
    generated_at: str = Field(default_factory=now_iso)
    provenance: str = CUSTOMER_SUPPLIED
    entity_counts: dict[str, int] = Field(default_factory=dict)
    parsed_entity_counts: dict[str, int] = Field(default_factory=dict)
    matched_count: int = 0
    new_count: int = 0
    conflict_count: int = 0
    summary: list[ProposalEntitySummary] = Field(default_factory=list)
    changes: list[ProposedChange] = Field(default_factory=list)
    control_boundary: ControlBoundary = Field(default_factory=ControlBoundary)


def build_proposal(
    reconcile_result: ReconcileResult,
    parse_result: ParseResult,
    *,
    source_file: str,
    upload_id: str | None = None,
    include_unchanged: bool = False,
) -> ChangeProposal:
    """Assemble a :class:`ChangeProposal` from the reconciler + parser output."""
    proposal = ChangeProposal(
        upload_id=upload_id,
        source_file=source_file,
        parser=parse_result.parser,
        parsed_entity_counts=parse_result.entity_counts(),
        matched_count=reconcile_result.matched_count,
        new_count=reconcile_result.new_count,
        conflict_count=reconcile_result.conflict_count,
    )

    summaries: dict[str, ProposalEntitySummary] = {}
    counts: dict[str, int] = {}
    for reconciled in reconcile_result.entities:
        counts[reconciled.entity_type] = counts.get(reconciled.entity_type, 0) + 1
        summary = summaries.setdefault(
            reconciled.entity_type, ProposalEntitySummary(entity_type=reconciled.entity_type)
        )
        summary.total += 1
        if reconciled.is_new:
            summary.new += 1
        else:
            summary.matched += 1
        if reconciled.conflict:
            summary.conflicts += 1

        record_id = reconciled.matched_record_id or reconciled.parsed_entity_id
        source_ref = f"{source_file}:line {reconciled.source_line}"
        for diff in reconciled.field_diffs:
            if diff.classification is FieldClassification.unchanged and not include_unchanged:
                continue
            proposal.changes.append(
                ProposedChange(
                    entity=reconciled.entity_type,
                    record_id=record_id,
                    field=diff.field,
                    current_value=diff.current_value,
                    proposed_value=diff.proposed_value,
                    source_ref=source_ref,
                    provenance=CUSTOMER_SUPPLIED,
                    match_confidence=reconciled.match_confidence,
                    conflict=diff.classification is FieldClassification.changed,
                )
            )

    proposal.entity_counts = counts
    proposal.summary = sorted(summaries.values(), key=lambda s: s.entity_type)
    return proposal
