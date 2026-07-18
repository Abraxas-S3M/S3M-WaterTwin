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
