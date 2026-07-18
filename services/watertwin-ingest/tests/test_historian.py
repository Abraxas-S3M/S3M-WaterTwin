"""Tests for the historian time-series parser."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from ot_ingestion.tag_normalization import TagMap

from app.parsers.historian import HistorianParseError, parse_historian
from app.provenance import IngestProvenance
from app.staging import StagingStore


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    lines = [",".join(header)]
    lines.extend(",".join(str(c) for c in row) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _staged_records(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def test_csv_import_stages_and_proposes_with_customer_measured(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    csv_path = tmp_path / "export.csv"
    _write_csv(
        csv_path,
        ["tag", "timestamp", "value", "quality"],
        [
            ["HIST.PT-101.PV", "2026-01-01T00:00:00+00:00", "61.2", "good"],
            ["HIST.FT-201.PV", "2026-01-01T00:05:00+00:00", "420.0", "good"],
        ],
    )

    result = parse_historian(csv_path, tag_map=tag_map, staging=staging)

    assert result.staged_rows == 2
    assert result.total_rows == 2
    assert result.unparsed_count == 0
    assert result.provenance == IngestProvenance.customer_measured.value

    # It produced a pending, approval-gated, read-only proposal (not a store write).
    proposal = result.proposal
    assert proposal.status.value == "pending"
    assert proposal.requires_operator_approval is True
    assert proposal.promotes_to_calibrated is False
    cb = proposal.control_boundary
    assert cb.control_mode == "advisory"
    assert cb.operator_approval_required is True
    assert cb.control_write_enabled is False

    records = _staged_records(result.staged.path)
    assert {r["asset_id"] for r in records} == {"AST-HPP-01", "AST-RO-01"}
    assert all(r["provenance"] == "customer_measured" for r in records)
    assert records[0]["timestamp"] == "2026-01-01T00:00:00+00:00"


def test_naive_timestamp_without_timezone_is_unparsed_not_assumed_utc(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    csv_path = tmp_path / "naive.csv"
    _write_csv(
        csv_path,
        ["tag", "timestamp", "value"],
        [["HIST.PT-101.PV", "2026-01-01T12:00:00", "61.2"]],
    )

    result = parse_historian(csv_path, tag_map=tag_map, staging=staging)

    assert result.staged_rows == 0
    assert result.unparsed_count == 1
    assert _staged_records(result.staged.path) == []
    codes = {w.code for w in result.warnings}
    assert "naive_timestamp_no_timezone" in codes


def test_declared_file_timezone_is_applied_and_not_utc(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    csv_path = tmp_path / "naive.csv"
    _write_csv(
        csv_path,
        ["tag", "timestamp", "value"],
        [["HIST.PT-101.PV", "2026-01-01T12:00:00", "61.2"]],
    )

    result = parse_historian(
        csv_path, tag_map=tag_map, staging=staging, file_timezone="America/New_York"
    )

    assert result.staged_rows == 1
    record = _staged_records(result.staged.path)[0]
    # Noon in New York in January (EST, UTC-5) is 17:00Z -- NOT the naive 12:00Z.
    assert datetime.fromisoformat(record["timestamp"]) == datetime(
        2026, 1, 1, 17, 0, tzinfo=UTC
    )


def test_ambiguous_local_time_is_a_warning_and_unparsed(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    # 2025-11-02 01:30 in America/New_York occurs twice (fall-back DST fold).
    csv_path = tmp_path / "ambiguous.csv"
    _write_csv(
        csv_path,
        ["tag", "timestamp", "value"],
        [["HIST.PT-101.PV", "2025-11-02T01:30:00", "61.2"]],
    )

    result = parse_historian(
        csv_path, tag_map=tag_map, staging=staging, file_timezone="America/New_York"
    )

    assert result.staged_rows == 0
    assert "ambiguous_local_time" in {w.code for w in result.warnings}


def test_per_row_timezone_column_is_honored(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    csv_path = tmp_path / "rowtz.csv"
    _write_csv(
        csv_path,
        ["tag", "timestamp", "value", "timezone"],
        [["HIST.PT-101.PV", "2026-06-01T00:00:00", "61.2", "+02:00"]],
    )

    result = parse_historian(csv_path, tag_map=tag_map, staging=staging)

    assert result.staged_rows == 1
    record = _staged_records(result.staged.path)[0]
    assert datetime.fromisoformat(record["timestamp"]) == datetime(
        2026, 5, 31, 22, 0, tzinfo=UTC
    )


def test_unmapped_tags_are_reported_not_guessed(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    csv_path = tmp_path / "unmapped.csv"
    _write_csv(
        csv_path,
        ["tag", "timestamp", "value"],
        [
            ["HIST.PT-101.PV", "2026-01-01T00:00:00+00:00", "61.2"],
            ["HIST.UNKNOWN.XYZ", "2026-01-01T00:00:00+00:00", "1.0"],
        ],
    )

    result = parse_historian(csv_path, tag_map=tag_map, staging=staging)

    assert result.unmapped_tags == ["HIST.UNKNOWN.XYZ"]
    assert result.staged_rows == 1
    records = _staged_records(result.staged.path)
    # The unmapped tag was never guessed into a canonical asset/metric.
    assert all(r["customer_tag"] != "HIST.UNKNOWN.XYZ" for r in records)


def test_non_numeric_and_non_finite_values_are_unparsed(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    csv_path = tmp_path / "bad_values.csv"
    _write_csv(
        csv_path,
        ["tag", "timestamp", "value"],
        [
            ["HIST.PT-101.PV", "2026-01-01T00:00:00+00:00", "not-a-number"],
            ["HIST.PT-101.PV", "2026-01-01T00:01:00+00:00", "inf"],
        ],
    )

    result = parse_historian(csv_path, tag_map=tag_map, staging=staging)

    assert result.staged_rows == 0
    assert result.unparsed_count == 2
    codes = {w.code for w in result.warnings}
    assert {"non_numeric_value", "non_finite_value"} <= codes


def test_missing_required_column_raises(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    csv_path = tmp_path / "bad_header.csv"
    _write_csv(csv_path, ["tag", "value"], [["HIST.PT-101.PV", "1.0"]])
    with pytest.raises(HistorianParseError):
        parse_historian(csv_path, tag_map=tag_map, staging=staging)


def test_no_gap_filling_or_resampling_or_interpolation(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    # Sparse, irregular timestamps: import exactly what is there, add nothing.
    csv_path = tmp_path / "sparse.csv"
    _write_csv(
        csv_path,
        ["tag", "timestamp", "value"],
        [
            ["HIST.PT-101.PV", "2026-01-01T00:00:00+00:00", "1.0"],
            ["HIST.PT-101.PV", "2026-01-01T06:00:00+00:00", "2.0"],
            ["HIST.PT-101.PV", "2026-01-02T00:00:00+00:00", "3.0"],
        ],
    )

    result = parse_historian(csv_path, tag_map=tag_map, staging=staging)

    assert result.staged_rows == 3  # no synthesized rows between the gaps
    assert result.proposal.summary["gap_filling"] == "none"
    assert result.proposal.summary["resampling"] == "none"
    assert result.proposal.summary["interpolation"] == "none"


def test_parquet_import_is_streamed_and_correct(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    parquet_path = tmp_path / "export.parquet"
    table = pa.table(
        {
            "tag": ["HIST.PT-101.PV", "HIST.FT-201.PV"],
            "timestamp": ["2026-01-01T00:00:00+00:00", "2026-01-01T00:05:00+00:00"],
            "value": [61.2, 420.0],
            "quality": ["good", "good"],
        }
    )
    pq.write_table(table, parquet_path)

    result = parse_historian(
        parquet_path, tag_map=tag_map, staging=staging, chunk_rows=1
    )

    assert result.file_format == "parquet"
    assert result.staged_rows == 2
    records = _staged_records(result.staged.path)
    assert all(r["provenance"] == "customer_measured" for r in records)
