"""Bulk-import parsers.

Each parser reads a customer-supplied file, resolves it against configuration,
writes the result to staging, and returns a result object carrying an approval
proposal plus everything that could not be parsed (reported, never guessed or
silently repaired).
"""

from __future__ import annotations

from .base import ParseWarning, UnparsedRecord
from .gis import GisParseError, GisParseResult, parse_gis
from .historian import HistorianParseError, HistorianParseResult, parse_historian

__all__ = [
    "GisParseError",
    "GisParseResult",
    "HistorianParseError",
    "HistorianParseResult",
    "ParseWarning",
    "UnparsedRecord",
    "parse_gis",
    "parse_historian",
]
