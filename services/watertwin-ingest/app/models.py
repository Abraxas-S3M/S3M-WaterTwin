"""Data-intake models: parse results, proposed changes and AI analysis items.

Central safety rule expressed in the type system: a :class:`ProposedChange` that
originates from the AI path is constructed via :meth:`ProposedChange.from_draft`,
which forces ``ai_suggested=True`` and ``accepted=False`` and *clamps* the
proposed provenance so an AI draft can never outrank the source file it cites.
There is no code path in this module that sets ``accepted=True`` implicitly; a
human must call :meth:`ProposedChange.accept` per field.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from canonical_water_model import DataProvenance, now_iso
from pydantic import BaseModel, Field

# Trust ordering for provenance labels (higher rank = more trustworthy). Used to
# guarantee an AI-drafted value never carries a label that outranks its source.
_PROVENANCE_RANK: dict[DataProvenance, int] = {
    DataProvenance.synthetic: 0,
    DataProvenance.simulated: 1,
    DataProvenance.estimated: 2,
    DataProvenance.preliminary: 3,
    DataProvenance.measured: 4,
}

# The highest provenance an AI-derived value may ever claim. An AI inference is,
# at best, a preliminary engineering estimate; it can never be labelled
# ``measured`` no matter how trustworthy its source document is.
AI_PROVENANCE_CEILING = DataProvenance.preliminary


def provenance_rank(provenance: DataProvenance) -> int:
    """Return the trust rank of a provenance label (higher = more trusted)."""
    return _PROVENANCE_RANK[provenance]


def clamp_ai_provenance(source_provenance: DataProvenance) -> DataProvenance:
    """Clamp an AI-derived provenance to never outrank ``source_provenance``.

    The result is the *lower* of the source file's provenance and the AI ceiling
    (:data:`AI_PROVENANCE_CEILING`). This is the invariant that stops the AI from
    ever "raising a provenance label": a draft citing a ``measured`` nameplate is
    still only ``preliminary``, and a draft citing ``synthetic`` seed data stays
    ``synthetic``.
    """
    if provenance_rank(source_provenance) <= provenance_rank(AI_PROVENANCE_CEILING):
        return source_provenance
    return AI_PROVENANCE_CEILING


class SourceCitation(BaseModel):
    """A citation that points at a *specific* source location.

    Every AI-derived item must carry one so a reviewer can see exactly where a
    claim came from (which document, and where inside it).
    """

    document_id: str
    #: Human-readable locator inside the source (e.g. "sheet 'Curve', row 12",
    #: "page 3, nameplate table", "line 42").
    locator: str
    snippet: str | None = None


class ParsedField(BaseModel):
    """A single field the parser was able to extract from a staged file."""

    field_path: str
    value: Any
    unit: str | None = None
    citation: SourceCitation | None = None


class ParseResult(BaseModel):
    """The deterministic parser's output for one staged file.

    ``content`` is the untrusted file body; it is never interpolated into an S3M
    prompt directly — the analysis layer always wraps it in the delimited
    untrusted-data block (see :mod:`app.untrusted`).
    """

    ingest_id: str
    source_filename: str
    content_type: str
    #: Provenance of the *source file* itself. AI drafts derived from this file
    #: are clamped so they can never outrank it.
    source_provenance: DataProvenance = DataProvenance.preliminary
    content: str = ""
    parsed_fields: list[ParsedField] = Field(default_factory=list)
    #: Field paths the parser could not fill (candidates for AI drafting).
    unparsed_fields: list[str] = Field(default_factory=list)

    def content_hash(self) -> str:
        """A stable hash of the parse result used as the analysis cache key.

        Folds in the identity + the parsed/unparsed field structure + the raw
        content so any change to what would be analyzed changes the key.
        """
        material = {
            "ingest_id": self.ingest_id,
            "source_filename": self.source_filename,
            "content_type": self.content_type,
            "source_provenance": self.source_provenance.value,
            "content": self.content,
            "parsed_fields": [f.model_dump(mode="json") for f in self.parsed_fields],
            "unparsed_fields": sorted(self.unparsed_fields),
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ProposedChange(BaseModel):
    """One reviewable diff row.

    An AI-suggested change is always created via :meth:`from_draft`, which forces
    ``ai_suggested=True`` and ``accepted=False``. Acceptance is only ever set by
    :meth:`accept`, which represents an explicit, per-field human opt-in.
    """

    change_id: str
    field_path: str
    current_value: Any = None
    proposed_value: Any = None
    provenance: DataProvenance = DataProvenance.preliminary

    # --- AI badge -----------------------------------------------------------
    ai_suggested: bool = False
    ai_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ai_rationale: str | None = None
    citation: SourceCitation | None = None

    # --- Acceptance state (defaults to UNACCEPTED) --------------------------
    accepted: bool = False
    accepted_by: str | None = None
    accepted_at: str | None = None

    @classmethod
    def from_draft(
        cls,
        *,
        change_id: str,
        field_path: str,
        proposed_value: Any,
        ai_confidence: float,
        ai_rationale: str,
        citation: SourceCitation,
        source_provenance: DataProvenance,
        current_value: Any = None,
    ) -> ProposedChange:
        """Build an AI-suggested change that DEFAULTS TO UNACCEPTED.

        The provenance is clamped via :func:`clamp_ai_provenance` so the draft can
        never outrank the source file it was derived from.
        """
        return cls(
            change_id=change_id,
            field_path=field_path,
            current_value=current_value,
            proposed_value=proposed_value,
            provenance=clamp_ai_provenance(source_provenance),
            ai_suggested=True,
            ai_confidence=max(0.0, min(1.0, ai_confidence)),
            ai_rationale=ai_rationale,
            citation=citation,
            accepted=False,
            accepted_by=None,
            accepted_at=None,
        )

    def accept(self, operator: str) -> ProposedChange:
        """Record an explicit, per-field human opt-in for this change.

        This is the ONLY place ``accepted`` becomes ``True``. It requires a named
        operator; the AI path never calls it.
        """
        if not operator or not operator.strip():
            raise ValueError("accepting a proposed change requires a named operator")
        self.accepted = True
        self.accepted_by = operator
        self.accepted_at = now_iso()
        return self


class AnalysisSummary(BaseModel):
    """Plain-language summary of what a staged file contains."""

    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    citation: SourceCitation


class AnomalyFlag(BaseModel):
    """An anomaly cross-checked against existing canonical config.

    Advisory only: an anomaly flag never changes data or provenance; it is a
    cited observation a human must act on.
    """

    code: str
    message: str
    severity: str = "info"
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    citation: SourceCitation
    #: Canonical references the flag was cross-checked against (e.g. asset ids).
    cross_references: list[str] = Field(default_factory=list)


class DraftedValue(BaseModel):
    """A value the AI drafted for a field the parser could not fill."""

    field_path: str
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    citation: SourceCitation


class AnalysisResult(BaseModel):
    """The full analysis payload for one staged file.

    ``available`` is ``False`` when S3M-Core could not be reached; in that case
    the summary/anomalies/drafts are empty and the caller renders the plain diff
    with a quiet notice (graceful degradation).
    """

    ingest_id: str
    parse_result_hash: str
    available: bool = True
    notice: str | None = None
    model_version: str | None = None
    source_engine_status: str
    generated_at: str = Field(default_factory=now_iso)

    summary: AnalysisSummary | None = None
    anomalies: list[AnomalyFlag] = Field(default_factory=list)
    drafted_values: list[DraftedValue] = Field(default_factory=list)
    #: AI-suggested diff rows (always ``accepted=False`` on arrival).
    proposed_changes: list[ProposedChange] = Field(default_factory=list)
