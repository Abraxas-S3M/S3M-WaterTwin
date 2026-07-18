"""Large-fixture streaming test: a ~500 MB historian export imports in bounded
memory.

The fixture is *generated* at test time (never committed) and written in a
streaming fashion so producing it does not itself blow up memory. The import is
then measured with :mod:`resource` peak-RSS growth and asserted to stay far
below the file size -- proof the parser streams rather than loading the file.
"""

from __future__ import annotations

import os
import resource
from pathlib import Path

import pytest
from ot_ingestion.tag_normalization import TagMap

from app.parsers.historian import parse_historian
from app.staging import StagingStore

#: Target fixture size. Overridable so constrained CI can shrink it; the default
#: exercises the true ~500 MB target from the acceptance criteria.
TARGET_BYTES = int(os.environ.get("WATERTWIN_HISTORIAN_FIXTURE_BYTES", str(500 * 1024 * 1024)))
#: Import must not grow resident memory by more than this (bounded-memory proof).
MAX_RSS_GROWTH_BYTES = 150 * 1024 * 1024


def _rss_bytes() -> int:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB; macOS reports bytes. Normalize to bytes.
    return rss * 1024 if rss < (1 << 40) else rss


def _generate_csv(path: Path, target_bytes: int) -> int:
    """Stream a large historian CSV to disk; return the row count written."""
    rows = 0
    written = 0
    with path.open("w", encoding="utf-8") as fh:
        header = "tag,timestamp,value,quality\n"
        fh.write(header)
        written += len(header)
        minute = 0
        while written < target_bytes:
            # Two mapped tags, explicit UTC offset (no timezone assumption).
            hh = (minute // 60) % 24
            mm = minute % 60
            ts = f"2026-01-01T{hh:02d}:{mm:02d}:00+00:00"
            line_a = f"HIST.PT-101.PV,{ts},{60 + (minute % 7)}.5,good\n"
            line_b = f"HIST.FT-201.PV,{ts},{400 + (minute % 11)}.0,good\n"
            fh.write(line_a)
            fh.write(line_b)
            written += len(line_a) + len(line_b)
            rows += 2
            minute += 1
    return rows


@pytest.mark.slow
def test_500mb_csv_imports_completely_in_bounded_memory(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    csv_path = tmp_path / "big-historian.csv"
    expected_rows = _generate_csv(csv_path, TARGET_BYTES)
    file_size = csv_path.stat().st_size
    assert file_size >= TARGET_BYTES * 0.9  # fixture really is large

    rss_before = _rss_bytes()
    result = parse_historian(csv_path, tag_map=tag_map, staging=staging)
    rss_after = _rss_bytes()

    assert result.total_rows == expected_rows
    assert result.staged_rows == expected_rows  # every mapped row landed
    assert result.unparsed_count == 0

    growth = rss_after - rss_before
    assert growth < MAX_RSS_GROWTH_BYTES, (
        f"RSS grew {growth / 1024 / 1024:.1f} MiB importing a "
        f"{file_size / 1024 / 1024:.1f} MiB file; parser is not streaming"
    )
