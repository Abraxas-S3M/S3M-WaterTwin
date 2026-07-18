"""The :class:`Parser` interface and the normalized :class:`ParseResult` shape.

Every file parser the ingest service grows (EPANET today; more formats later)
implements :class:`Parser` and returns a :class:`ParseResult`.

Design contract — **partial success is a normal outcome, not an error**:

* A parser MUST NOT raise on malformed input. It returns what it could read
  (``entities``), plus what it could not (``unparsed``, each with a source line
  number and a plain-language ``reason``), plus advisory ``warnings`` and
  ``stats``.
* Every parsed entity records the *source line number* it came from so a
  reviewer can trace any proposed value back to ``file:line``.
* Hydraulic quantities are unit-bearing: when the source units are unknown or
  ambiguous a parser NEVER guesses — it emits a warning and routes the affected
  fields to ``unparsed``.
"""

from __future__ import annotations

import abc
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

#: The canonical unit system every parser normalizes hydraulic quantities to.
#: The canonical water model is SI: flow in m3/h, lengths in m, pipe/valve
#: diameters in mm, elevations/heads/levels in m.
CANONICAL_UNITS = "SI (m3/h, m, mm)"


class ParseStatus(str, Enum):
    """Outcome of a parse.

    ``parsed`` — everything requested was read. ``partial`` — some content was
    read and some routed to ``unparsed`` (a normal, non-error outcome).
    ``parse_failed`` — the worker crashed, timed out, or the input was rejected
    before parsing (e.g. an XXE attempt); ``ParseResult.error`` explains why.
    """

    parsed = "parsed"
    partial = "partial"
    parse_failed = "parse_failed"


class ParseScope(BaseModel):
    """What the human confirmed should be extracted from an uploaded file.

    ``file_format`` is the confirmed classification (e.g. ``"epanet"``).
    ``sections`` optionally restricts extraction to specific source sections;
    empty means "all sections this parser understands". The scope is supplied by
    a human via the ``classify`` endpoint — a critical-infrastructure file is
    never parsed on a sniffed guess alone.
    """

    file_format: str
    sections: list[str] = Field(default_factory=list)
    note: str | None = None


class ParsedEntity(BaseModel):
    """A single normalized entity read from the source file.

    ``fields`` holds the normalized (canonical-unit) attributes. ``source_line``
    is the 1-based line number the entity was defined on. ``provenance`` records
    where the values came from — always ``customer_supplied`` for an uploaded
    customer file.
    """

    entity_type: str
    entity_id: str
    name: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    source_line: int
    provenance: str = "customer_supplied"


class ParseWarning(BaseModel):
    """A non-fatal advisory raised during parsing (never a silent drop)."""

    message: str
    section: str | None = None
    line: int | None = None


class UnparsedItem(BaseModel):
    """Content that could not be read, with a line number and a plain reason."""

    line: int
    reason: str
    section: str | None = None
    raw: str | None = None
    entity_id: str | None = None
    field: str | None = None


class ParseStats(BaseModel):
    """Summary counters for a parse (surfaced alongside the result)."""

    total_lines: int = 0
    sections_seen: list[str] = Field(default_factory=list)
    entities_by_type: dict[str, int] = Field(default_factory=dict)
    entity_count: int = 0
    warning_count: int = 0
    unparsed_count: int = 0
    duration_s: float = 0.0
    source_units: str | None = None
    normalized_to: str | None = None


class ParseResult(BaseModel):
    """The normalized output of a parse (see the module docstring for the contract)."""

    status: ParseStatus
    parser: str
    entities: list[ParsedEntity] = Field(default_factory=list)
    warnings: list[ParseWarning] = Field(default_factory=list)
    unparsed: list[UnparsedItem] = Field(default_factory=list)
    stats: ParseStats = Field(default_factory=ParseStats)
    error: str | None = None

    def entity_counts(self) -> dict[str, int]:
        """Return the number of parsed entities grouped by ``entity_type``."""
        counts: dict[str, int] = {}
        for entity in self.entities:
            counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
        return counts

    def finalize(self, *, duration_s: float) -> ParseResult:
        """Populate derived stats and settle the ``parsed``/``partial`` status.

        Called by a parser just before returning. Does not downgrade an already
        ``parse_failed`` status.
        """
        counts = self.entity_counts()
        self.stats.entities_by_type = counts
        self.stats.entity_count = len(self.entities)
        self.stats.warning_count = len(self.warnings)
        self.stats.unparsed_count = len(self.unparsed)
        self.stats.duration_s = duration_s
        self.stats.normalized_to = CANONICAL_UNITS
        if self.status is not ParseStatus.parse_failed:
            self.status = ParseStatus.partial if self.unparsed else ParseStatus.parsed
        return self


class Parser(abc.ABC):
    """Interface every file parser implements.

    A parser is a pure, offline transform: given a path to an uploaded file and
    the human-confirmed :class:`ParseScope`, it returns a :class:`ParseResult`.
    It must never raise on malformed input and must never perform any network or
    control I/O.
    """

    #: Stable identifier of the file format this parser handles (e.g. ``epanet``).
    file_format: str = "base"
    #: Human/CI readable name recorded in :attr:`ParseResult.parser`.
    name: str = "base-parser"

    @abc.abstractmethod
    def parse(self, path: str, scope: ParseScope) -> ParseResult:
        """Parse ``path`` within ``scope`` and return a :class:`ParseResult`."""
        raise NotImplementedError

    @staticmethod
    def failure(parser: str, message: str) -> ParseResult:
        """Build a ``parse_failed`` result carrying a useful message."""
        return ParseResult(status=ParseStatus.parse_failed, parser=parser, error=message)
"""Shared parser primitives: warnings and unparsed-record reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParseWarning:
    """A non-fatal issue surfaced to the operator (never silently dropped)."""

    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": self.detail}


@dataclass(frozen=True)
class UnparsedRecord:
    """A record that could not be parsed, kept with the reason and its location.

    ``raw`` is a best-effort, size-bounded snapshot of the offending record so an
    operator can see what was rejected without the parser having to hold the
    whole file in memory.
    """

    reason: str
    location: str
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "location": self.location, "raw": self.raw}
