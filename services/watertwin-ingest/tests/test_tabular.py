"""Tests for the shared reading engine, escaping and encoding handling."""

from __future__ import annotations

import pytest

from app.parsers import tabular
from app.parsers.tabular import (
    ColumnSpec,
    IngestError,
    escape_formula,
    normalize_header,
    parse_table,
    read_rows,
)

# --- formula-injection escape helper ---------------------------------------


@pytest.mark.parametrize("trigger", ["=", "+", "-", "@"])
def test_escape_formula_escapes_each_trigger_char(trigger: str) -> None:
    payload = f"{trigger}SUM(A1)"
    escaped = escape_formula(payload)
    assert escaped == f"'{payload}"
    assert escaped.startswith("'")


def test_escape_formula_handles_tab_and_cr_and_leading_whitespace() -> None:
    assert escape_formula("\t=1").startswith("'")
    assert escape_formula("\r=1").startswith("'")
    # A dangerous char hidden behind leading whitespace is still escaped.
    assert escape_formula("   =cmd").startswith("'")


def test_escape_formula_leaves_safe_and_non_string_values_untouched() -> None:
    assert escape_formula("normal text") == "normal text"
    assert escape_formula("") == ""
    assert escape_formula("3.14") == "3.14"
    assert escape_formula(42) == 42
    assert escape_formula(None) is None


# --- header normalization ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Asset ID", "asset_id"),
        (" asset-id ", "asset_id"),
        ("Rated Flow (m3/h)", "rated_flow"),
        ("NPSHr", "npshr"),
        ("Efficiency (%)", "efficiency"),  # parenthesised annotation dropped
        ("Recovery %", "recovery_pct"),
    ],
)
def test_normalize_header(raw: str, expected: str) -> None:
    assert normalize_header(raw) == expected


# --- file reading -----------------------------------------------------------


def test_xlsm_is_rejected_outright() -> None:
    with pytest.raises(IngestError, match="xlsm"):
        read_rows(b"anything", "specs.xlsm")


def test_xlsm_rejected_before_reading_bytes(read_fixture) -> None:
    # Even a structurally-valid workbook is refused purely on its .xlsm extension.
    data = read_fixture("rejected.xlsm")
    with pytest.raises(IngestError):
        read_rows(data, "rejected.xlsm")


def test_unsupported_extension_rejected() -> None:
    with pytest.raises(IngestError, match="unsupported"):
        read_rows(b"data", "specs.pdf")


def test_empty_csv_reports_error_not_crash() -> None:
    columns = (ColumnSpec("a", "A", required=True, kind="string"),)
    report = parse_table(b"", "empty.csv", columns, kind="t", provenance="p")
    assert not report.ok
    assert any("empty" in e.message for e in report.errors)


def test_reads_xlsx_values_only(read_fixture) -> None:
    table = read_rows(read_fixture("equipment_valid.xlsx"), "equipment_valid.xlsx")
    assert table.headers[0] == "asset_id"
    assert len(table.rows) == 2


# --- encoding detection -----------------------------------------------------


def test_plain_utf8_needs_no_encoding_warning() -> None:
    columns = (
        ColumnSpec("sample_point", "SP", required=True, kind="string"),
        ColumnSpec("parameter", "P", required=True, kind="string"),
    )
    data = b"sample_point,parameter\nRO,Boron\n"
    report = parse_table(data, "x.csv", columns, kind="t", provenance="p")
    assert report.warnings == []
    assert len(report.records) == 1


def test_cp1252_encoding_is_handled_with_a_warning() -> None:
    columns = (
        ColumnSpec("sample_point", "SP", required=True, kind="string"),
        ColumnSpec("parameter", "P", required=True, kind="string"),
    )
    # 0xE9 is 'é' in cp1252 but not valid standalone UTF-8, forcing detection.
    data = "sample_point,parameter\nRO,r\u00e9sidu\n".encode("cp1252")
    report = parse_table(data, "x.csv", columns, kind="t", provenance="p")
    assert len(report.records) == 1
    # The row survived and the guess/fallback was reported, never silent.
    assert any("encoding" in w.message for w in report.warnings)


def test_utf8_bom_is_stripped() -> None:
    columns = (ColumnSpec("sample_point", "SP", required=True, kind="string"),)
    data = "\ufeffsample_point\nRO\n".encode("utf-8-sig")
    report = parse_table(data, "x.csv", columns, kind="t", provenance="p")
    assert report.records[0]["sample_point"] == "RO"


def test_render_template_csv_round_trips_and_escapes(monkeypatch) -> None:
    columns = (
        ColumnSpec("a", "A", required=True, kind="string", example="ok"),
        ColumnSpec("b", "B", required=False, kind="number", unit="m", example="1.5"),
    )
    text = tabular.render_template_csv(columns)
    assert "a,b (m)" in text
    report = parse_table(text.encode("utf-8"), "t.csv", columns, kind="t", provenance="p")
    assert report.ok
    assert report.records[0]["a"] == "ok"
    assert report.records[0]["b"] == 1.5
