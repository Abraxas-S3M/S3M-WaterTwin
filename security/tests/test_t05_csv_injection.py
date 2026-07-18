"""ADR-0014 T5 — CSV formula injection on export.

Control: every exported cell that begins with a formula trigger (``= + - @`` or a
leading tab/CR) is neutralised (prefixed with a single quote) so a spreadsheet
cannot execute it.
"""

from __future__ import annotations

import csv
import io

import pytest
from app.csv_safe import escape_cell, is_dangerous, write_csv

DANGEROUS = [
    "=1+1",
    "+1",
    "-1+1",
    "@SUM(A1:A9)",
    "=cmd|'/c calc'!A1",
    "\t=1",
    "\r=1",
]


@pytest.mark.parametrize("value", DANGEROUS)
def test_dangerous_cells_are_flagged(value):
    assert is_dangerous(value) is True


@pytest.mark.parametrize("value", DANGEROUS)
def test_dangerous_cells_are_escaped(value):
    escaped = escape_cell(value)
    assert escaped.startswith("'")
    # Re-reading the exported cell yields the neutralised text, never a formula.
    assert not is_dangerous(escaped)


def test_benign_cells_untouched():
    assert escape_cell("turbidity") == "turbidity"
    assert escape_cell("0.3") == "0.3"
    assert escape_cell(None) == ""


def test_write_csv_escapes_every_formula_cell():
    rows = [["analyte", "value"], ["=HYPERLINK(x)", "@evil"]]
    out = write_csv(rows)
    parsed = list(csv.reader(io.StringIO(out)))
    assert parsed[1][0].startswith("'=")
    assert parsed[1][1].startswith("'@")
    # No exported cell is interpretable as a formula.
    for row in parsed:
        for cell in row:
            assert not is_dangerous(cell)
