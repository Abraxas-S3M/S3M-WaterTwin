"""CSV formula-injection-safe export.

When platform data is exported back to CSV (e.g. a tenant downloading their
parsed lab results), any cell whose value begins with a formula trigger
(``= + - @`` or a leading tab/carriage-return) is neutralised so a spreadsheet
application cannot execute it as a formula (CSV/Formula injection, aka CSV
injection). The neutralisation prefixes the cell with a single quote and quotes
the field, which is the OWASP-recommended mitigation and is lossless on import.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence

#: Characters that make a spreadsheet treat a cell as a formula.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def escape_cell(value: object) -> str:
    """Return ``value`` as a spreadsheet-safe cell string.

    A cell that starts with a formula trigger is prefixed with a single quote so
    the spreadsheet renders it as literal text instead of evaluating it.
    """
    text = "" if value is None else str(value)
    if text and text[0] in _FORMULA_TRIGGERS:
        return "'" + text
    return text


def is_dangerous(value: object) -> bool:
    """True iff ``value`` would be interpreted as a formula by a spreadsheet."""
    text = "" if value is None else str(value)
    return bool(text) and text[0] in _FORMULA_TRIGGERS


def write_csv(rows: Iterable[Sequence[object]]) -> str:
    """Serialise ``rows`` to CSV text with every cell formula-injection-escaped."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    for row in rows:
        writer.writerow([escape_cell(cell) for cell in row])
    return buffer.getvalue()
