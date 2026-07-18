"""Tests for the templated laboratory-method parser."""

from __future__ import annotations

from app.parsers import lab


def test_happy_path_csv_template() -> None:
    report = lab.parse(lab.template_csv().encode("utf-8"), "lab_methods_template.csv")
    assert report.ok
    record = report.records[0]
    assert record["sample_point"] == "RO-PERMEATE"
    assert record["parameter"] == "Boron"
    assert record["provenance"] == "customer_supplied"


def test_missing_required_column_names_the_column() -> None:
    data = b"sample_point,parameter,unit\nRO,Boron,mg/L\n"
    report = lab.parse(data, "lab.csv")
    assert not report.ok
    assert any("method" in e.message for e in report.errors)


def test_negative_lod_out_of_range() -> None:
    data = b"sample_point,parameter,method,unit,lod\nRO,Boron,ICP,mg/L,-0.1\n"
    report = lab.parse(data, "lab.csv")
    assert not report.ok
    assert "lod" in report.errors[0].message


def test_loq_below_lod_is_flagged() -> None:
    data = b"sample_point,parameter,method,unit,lod,loq\nRO,Boron,ICP,mg/L,0.05,0.02\n"
    report = lab.parse(data, "lab.csv")
    assert not report.ok
    assert len(report.records) == 0
    assert any("LOQ" in e.message and "LOD" in e.message for e in report.errors)


def test_one_bad_row_does_not_discard_others(read_fixture) -> None:
    # The fixture middle row has a blank (required) method; the other two survive.
    report = lab.parse(read_fixture("lab_valid_with_bad_row.csv"), "lab_valid_with_bad_row.csv")
    assert len(report.records) == 2
    assert {r["parameter"] for r in report.records} == {"Boron", "TDS"}
    assert any(e.row == 3 for e in report.errors)


def test_mixed_encoding_is_handled_with_warning(read_fixture) -> None:
    report = lab.parse(read_fixture("lab_cp1252.csv"), "lab_cp1252.csv")
    assert len(report.records) == 1
    # Non-UTF-8 bytes are decoded (detected/fallback), never dropped silently.
    assert any("encoding" in w.message for w in report.warnings)
    assert "sidu" in report.records[0]["parameter"]


def test_unknown_column_ignored_not_fatal() -> None:
    data = b"sample_point,parameter,method,unit,accreditation\nRO,Boron,ICP,mg/L,ISO17025\n"
    report = lab.parse(data, "lab.csv")
    assert report.ok
    assert any("accreditation" in w.message for w in report.warnings)


def test_generated_template_round_trips_cleanly() -> None:
    report = lab.parse(lab.template_csv().encode("utf-8"), "lab_methods_template.csv")
    assert report.ok
    assert report.warnings == []
    assert len(report.records) == 1
