"""Tests for the templated equipment-specification parser."""

from __future__ import annotations

from app.parsers import equipment


def test_happy_path_csv_template() -> None:
    report = equipment.parse(equipment.template_csv().encode("utf-8"), "equipment_template.csv")
    assert report.ok
    assert len(report.records) == 1
    record = report.records[0]
    assert record["asset_id"] == "AST-HPP-01"
    assert record["rated_flow_m3h"] == 420.0
    assert record["provenance"] == "vendor_specified"


def test_happy_path_xlsx_fixture(read_fixture) -> None:
    report = equipment.parse(read_fixture("equipment_valid.xlsx"), "equipment_valid.xlsx")
    assert report.ok
    assert len(report.records) == 2
    assert all(r["provenance"] == "vendor_specified" for r in report.records)


def test_missing_required_column_names_the_column() -> None:
    report = equipment.parse(b"name,type\nPump,hp_pump\n", "specs.csv")
    assert not report.ok
    assert len(report.records) == 0
    messages = " ".join(e.message for e in report.errors)
    assert "asset_id" in messages


def test_unknown_column_is_warned_ignored_not_fatal() -> None:
    data = b"asset_id,name,type,favourite_colour\nAST-1,Pump,hp_pump,blue\n"
    report = equipment.parse(data, "specs.csv")
    assert report.ok  # not fatal
    assert len(report.records) == 1
    assert "favourite_colour" not in report.records[0]
    assert any("favourite_colour" in w.message for w in report.warnings)


def test_out_of_range_head_flagged_with_specific_range() -> None:
    data = b"asset_id,name,type,rated_head_m (m)\nAST-1,Pump,hp_pump,10000\n"
    report = equipment.parse(data, "specs.csv")
    assert not report.ok
    assert len(report.records) == 0
    msg = report.errors[0].message
    assert "out of range" in msg
    assert "0 < value <= 1000 (m)" in msg


def test_efficiency_above_one_flagged() -> None:
    data = b"asset_id,name,type,efficiency (fraction)\nAST-1,Pump,hp_pump,1.5\n"
    report = equipment.parse(data, "specs.csv")
    assert not report.ok
    assert "0 < value <= 1 (fraction)" in report.errors[0].message


def test_negative_npshr_flagged() -> None:
    data = b"asset_id,name,type,npshr_m (m)\nAST-1,Pump,hp_pump,-2\n"
    report = equipment.parse(data, "specs.csv")
    assert not report.ok
    assert "npshr_m" in report.errors[0].message


def test_one_bad_cell_does_not_discard_other_rows() -> None:
    data = (
        b"asset_id,name,type,npshr_m (m)\n"
        b"AST-1,Pump A,hp_pump,-5\n"      # bad: negative NPSHr
        b"AST-2,Pump B,hp_pump,3.0\n"     # good
        b"AST-3,Pump C,hp_pump,4.0\n"     # good
    )
    report = equipment.parse(data, "specs.csv")
    assert len(report.records) == 2
    assert {r["asset_id"] for r in report.records} == {"AST-2", "AST-3"}
    assert len(report.errors) == 1
    assert report.errors[0].row == 2


def test_out_of_range_xlsx_rows_are_flagged_survivor_kept(read_fixture) -> None:
    report = equipment.parse(
        read_fixture("equipment_out_of_range.xlsx"), "equipment_out_of_range.xlsx"
    )
    assert len(report.records) == 1
    assert report.records[0]["asset_id"] == "AST-HPP-01"
    assert len(report.errors) == 2  # the 10000 m head and the negative NPSHr


def test_generated_template_round_trips_cleanly() -> None:
    report = equipment.parse(equipment.template_csv().encode("utf-8"), "equipment_template.csv")
    assert report.ok
    assert report.warnings == []
    assert len(report.records) == 1
