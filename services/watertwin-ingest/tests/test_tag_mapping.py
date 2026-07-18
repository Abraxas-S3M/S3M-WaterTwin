"""Tests for the templated OT tag-mapping parser."""

from __future__ import annotations

from app.parsers import tag_mapping


def test_happy_path_csv_template() -> None:
    report = tag_mapping.parse(
        tag_mapping.template_csv().encode("utf-8"), "tag_mapping_template.csv"
    )
    assert report.ok
    record = report.records[0]
    assert record["ot_tag"] == "PLC1.HPP01.FLOW"
    assert record["asset_id"] == "AST-HPP-01"
    assert record["scale"] == 1.0
    assert record["provenance"] == "customer_supplied"


def test_happy_path_xlsx_fixture(read_fixture) -> None:
    report = tag_mapping.parse(read_fixture("tag_mapping_valid.xlsx"), "tag_mapping_valid.xlsx")
    assert report.ok
    assert len(report.records) == 2


def test_missing_required_unit_column_names_the_column() -> None:
    data = b"ot_tag,asset_id,measurement_type\nT1,AST-1,flow\n"
    report = tag_mapping.parse(data, "tags.csv")
    assert not report.ok
    assert any("unit" in e.message for e in report.errors)


def test_optional_scale_defaults_when_blank() -> None:
    data = b"ot_tag,asset_id,measurement_type,unit\nT1,AST-1,flow,m3/h\n"
    report = tag_mapping.parse(data, "tags.csv")
    assert report.ok
    assert report.records[0]["scale"] == 1.0
    assert report.records[0]["offset"] == 0.0


def test_negative_deadband_flagged() -> None:
    data = b"ot_tag,asset_id,measurement_type,unit,deadband\nT1,AST-1,flow,m3/h,-1\n"
    report = tag_mapping.parse(data, "tags.csv")
    assert not report.ok
    assert "deadband" in report.errors[0].message


def test_scale_out_of_range_flagged_with_range() -> None:
    data = b"ot_tag,asset_id,measurement_type,unit,scale\nT1,AST-1,flow,m3/h,9999999\n"
    report = tag_mapping.parse(data, "tags.csv")
    assert not report.ok
    assert "out of range" in report.errors[0].message


def test_unit_bearing_value_is_ambiguous_warned_and_unparsed() -> None:
    # An optional numeric carrying a unit ("50 psi") is ambiguous: warn, drop the
    # value to its default, but keep the row.
    data = b"ot_tag,asset_id,measurement_type,unit,scale\nT1,AST-1,flow,m3/h,50 psi\n"
    report = tag_mapping.parse(data, "tags.csv")
    assert report.ok
    assert any("unparsed" in w.message for w in report.warnings)
    assert report.records[0]["scale"] == 1.0


def test_unknown_column_ignored_not_fatal() -> None:
    data = b"ot_tag,asset_id,measurement_type,unit,notes\nT1,AST-1,flow,m3/h,hello\n"
    report = tag_mapping.parse(data, "tags.csv")
    assert report.ok
    assert any("notes" in w.message for w in report.warnings)


def test_generated_template_round_trips_cleanly() -> None:
    report = tag_mapping.parse(
        tag_mapping.template_csv().encode("utf-8"), "tag_mapping_template.csv"
    )
    assert report.ok
    assert report.warnings == []
    assert len(report.records) == 1
