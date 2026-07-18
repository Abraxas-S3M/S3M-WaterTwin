"""Historian time-series export parser (``.csv`` / ``.parquet``).

Design constraints (all enforced by tests):

* **Streamed / chunked.** Neither format is ever fully materialized in memory;
  CSV is read row-by-row and Parquet is read in record batches. A ~500 MB file
  imports in bounded memory.
* **Explicit timezones.** Every timestamp must carry an explicit offset, come
  with a per-row ``timezone`` column, or fall under a declared file-level
  timezone. Naive or ambiguous timestamps are a **warning** and their rows go to
  *unparsed* -- we never assume UTC on plant data.
* **No tag guessing.** Tags are resolved through the shared tag-mapping
  configuration; unmapped tags are reported, never inferred.
* **Provenance is ``customer_measured``** and importing NEVER promotes an
  analytic from ``preliminary`` to ``calibrated``.
* **No gap filling / resampling / interpolation.** Import what is there; report
  what is missing.

The parser writes staged rows to :class:`~app.staging.StagingStore` and returns
an :class:`~app.proposals.ImportProposal`; it does not push into the analytic
store.
"""

from __future__ import annotations

import csv
import math
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ot_ingestion.tag_normalization import TagMap

from ..proposals import PROPOSAL_TIMESERIES_IMPORT, ImportProposal
from ..provenance import IngestProvenance
from ..staging import StagedArtifact, StagingStore
from .base import ParseWarning, UnparsedRecord

#: Default Parquet record-batch size (rows). Bounds peak memory during import.
DEFAULT_CHUNK_ROWS = 50_000
#: Cap on retained unparsed-record samples (full counts are always exact).
MAX_UNPARSED_SAMPLE = 1_000

_TAG_ALIASES = {"tag", "tagname", "tag_name", "point", "pointname", "point_name"}
_TIMESTAMP_ALIASES = {"timestamp", "time", "datetime", "date_time", "ts"}
_VALUE_ALIASES = {"value", "val", "reading", "measurement"}
_QUALITY_ALIASES = {"quality", "qual", "q", "status"}
_TIMEZONE_ALIASES = {"timezone", "tz", "time_zone"}


class HistorianParseError(ValueError):
    """Raised for unrecoverable problems (unknown format, missing columns)."""


@dataclass
class HistorianParseResult:
    """Outcome of a historian import: the staged artifact, proposal, and reports."""

    dataset_id: str
    file_format: str
    provenance: str
    file_timezone: str | None
    staged: StagedArtifact
    proposal: ImportProposal
    total_rows: int
    staged_rows: int
    unparsed_count: int
    unparsed_sample: list[UnparsedRecord] = field(default_factory=list)
    unmapped_tags: list[str] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)
    #: Importing historian data never validates/calibrates an analytic.
    promotes_to_calibrated: bool = False

    @property
    def analytic_labels_changed(self) -> bool:
        """Always ``False`` -- import touches staging only, never analytics."""
        return False


def _load_zone(name: str) -> timezone | ZoneInfo:
    """Resolve an IANA zone name or a fixed ``+HH:MM`` offset to a tzinfo."""
    text = name.strip()
    if text.upper() in ("UTC", "Z"):
        return UTC
    if text and text[0] in "+-" and ":" in text:
        sign = 1 if text[0] == "+" else -1
        hours, _, minutes = text[1:].partition(":")
        return timezone(sign * timedelta(hours=int(hours), minutes=int(minutes)))
    return ZoneInfo(text)


def _parse_timestamp(raw: Any) -> datetime | None:
    """Parse a raw timestamp cell into a ``datetime`` (aware or naive), or None."""
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day)
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _resolve_instant(
    raw_ts: Any,
    row_tz: str | None,
    file_tz: str | None,
) -> tuple[str | None, str | None]:
    """Resolve a timestamp to an explicit UTC ISO string, or a warning code.

    Returns ``(iso_utc, None)`` on success or ``(None, warning_code)`` when the
    instant cannot be pinned down without *assuming* a timezone.
    """
    dt = _parse_timestamp(raw_ts)
    if dt is None:
        return None, "unparsable_timestamp"
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).isoformat(), None

    tz_name = (row_tz or "").strip() or (file_tz or "").strip()
    if not tz_name:
        return None, "naive_timestamp_no_timezone"
    try:
        zone = _load_zone(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None, "unknown_timezone"

    aware_early = dt.replace(tzinfo=zone, fold=0)
    aware_late = dt.replace(tzinfo=zone, fold=1)
    if aware_early.utcoffset() != aware_late.utcoffset():
        return None, "ambiguous_local_time"
    utc = aware_early.astimezone(UTC)
    if utc.astimezone(zone).replace(tzinfo=None) != dt:
        return None, "nonexistent_local_time"
    return utc.isoformat(), None


def _resolve_columns(header: list[str]) -> dict[str, int]:
    """Map logical column roles to positional indices from a header row."""
    index: dict[str, int] = {}
    for pos, name in enumerate(header):
        key = str(name).strip().lower()
        if key in _TAG_ALIASES and "tag" not in index:
            index["tag"] = pos
        elif key in _TIMESTAMP_ALIASES and "timestamp" not in index:
            index["timestamp"] = pos
        elif key in _VALUE_ALIASES and "value" not in index:
            index["value"] = pos
        elif key in _QUALITY_ALIASES and "quality" not in index:
            index["quality"] = pos
        elif key in _TIMEZONE_ALIASES and "timezone" not in index:
            index["timezone"] = pos
    missing = [c for c in ("tag", "timestamp", "value") if c not in index]
    if missing:
        raise HistorianParseError(
            f"historian export is missing required column(s): {missing}; "
            f"found header {header!r}"
        )
    return index


class _Accumulator:
    """Mutable per-import counters shared across streamed rows."""

    def __init__(self) -> None:
        self.total = 0
        self.staged = 0
        self.unparsed = 0
        self.unparsed_sample: list[UnparsedRecord] = []
        self.unmapped_tags: set[str] = set()
        self.warning_counts: Counter[str] = Counter()

    def reject(self, reason: str, location: str, raw: dict[str, Any]) -> None:
        self.unparsed += 1
        self.warning_counts[reason] += 1
        if len(self.unparsed_sample) < MAX_UNPARSED_SAMPLE:
            self.unparsed_sample.append(UnparsedRecord(reason, location, raw))


def _handle_row(
    acc: _Accumulator,
    tag_map: TagMap,
    writer: Any,
    *,
    tag: Any,
    timestamp: Any,
    value: Any,
    quality: Any,
    row_tz: Any,
    file_tz: str | None,
    location: str,
) -> None:
    """Resolve and stage one logical row, or route it to the unparsed report."""
    acc.total += 1
    tag_str = None if tag is None else str(tag).strip()
    if not tag_str:
        acc.reject("missing_tag", location, {"tag": tag})
        return

    entry = tag_map.entries.get(tag_str)
    if entry is None:
        acc.unmapped_tags.add(tag_str)
        acc.reject("unmapped_tag", location, {"tag": tag_str})
        return

    iso_utc, tz_warning = _resolve_instant(
        timestamp, None if row_tz is None else str(row_tz), file_tz
    )
    if iso_utc is None:
        acc.reject(tz_warning or "unparsable_timestamp", location, {"timestamp": str(timestamp)})
        return

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        acc.reject("non_numeric_value", location, {"tag": tag_str, "value": str(value)})
        return
    if not math.isfinite(numeric):
        acc.reject("non_finite_value", location, {"tag": tag_str, "value": str(value)})
        return

    quality_str = None if quality is None or str(quality).strip() == "" else str(quality).strip()
    writer.append(
        {
            "asset_id": entry.asset_id,
            "metric": entry.metric,
            "value": numeric * entry.scale + entry.offset,
            "unit": entry.unit,
            "timestamp": iso_utc,
            "provenance": IngestProvenance.customer_measured.value,
            "quality": quality_str,
            "customer_tag": tag_str,
        }
    )
    acc.staged += 1


def _cell(row: list[str], idx: int | None) -> Any:
    """Return ``row[idx]`` or ``None`` when the column is absent/short."""
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _stream_csv(
    path: Path,
    acc: _Accumulator,
    tag_map: TagMap,
    writer: Any,
    file_tz: str | None,
) -> None:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            raise HistorianParseError("historian CSV is empty (no header row)")
        cols = _resolve_columns([str(c) for c in header])
        tz_idx = cols.get("timezone")
        q_idx = cols.get("quality")
        tag_idx = cols["tag"]
        ts_idx = cols["timestamp"]
        val_idx = cols["value"]
        for line_no, row in enumerate(reader, start=2):
            if not row:
                continue
            _handle_row(
                acc,
                tag_map,
                writer,
                tag=_cell(row, tag_idx),
                timestamp=_cell(row, ts_idx),
                value=_cell(row, val_idx),
                quality=_cell(row, q_idx),
                row_tz=_cell(row, tz_idx),
                file_tz=file_tz,
                location=f"row {line_no}",
            )


def _stream_parquet(
    path: Path,
    acc: _Accumulator,
    tag_map: TagMap,
    writer: Any,
    file_tz: str | None,
    chunk_rows: int,
) -> None:
    import pyarrow.parquet as pq

    parquet_file = pq.ParquetFile(str(path))
    schema_names = list(parquet_file.schema_arrow.names)
    cols = _resolve_columns(schema_names)
    selected = sorted({schema_names[i] for i in cols.values()})
    name_for = {role: schema_names[idx] for role, idx in cols.items()}

    row_base = 2
    for batch in parquet_file.iter_batches(batch_size=chunk_rows, columns=selected):
        data = {role: batch.column(name).to_pylist() for role, name in name_for.items()}
        rows = batch.num_rows
        for r in range(rows):
            _handle_row(
                acc,
                tag_map,
                writer,
                tag=data["tag"][r],
                timestamp=data["timestamp"][r],
                value=data["value"][r],
                quality=data["quality"][r] if "quality" in data else None,
                row_tz=data["timezone"][r] if "timezone" in data else None,
                file_tz=file_tz,
                location=f"row {row_base + r}",
            )
        row_base += rows


def parse_historian(
    path: str | Path,
    *,
    tag_map: TagMap,
    staging: StagingStore,
    file_timezone: str | None = None,
    dataset_id: str | None = None,
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
) -> HistorianParseResult:
    """Stream-parse a historian export into staging and build an import proposal.

    ``file_timezone`` declares a file-level timezone used only for rows whose
    timestamp is naive and carry no per-row ``timezone``. It is never defaulted
    to UTC.
    """
    src = Path(path)
    suffix = src.suffix.lower()
    if suffix == ".csv":
        file_format = "csv"
    elif suffix in (".parquet", ".pq"):
        file_format = "parquet"
    else:
        raise HistorianParseError(f"unsupported historian format: {src.suffix!r}")

    if file_timezone is not None:
        # Validate the declared zone up-front so a typo fails loudly, not silently.
        try:
            _load_zone(file_timezone)
        except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
            raise HistorianParseError(f"unknown file_timezone {file_timezone!r}") from exc

    resolved_id = dataset_id or f"{src.stem or 'historian'}-{uuid.uuid4().hex[:8]}"
    acc = _Accumulator()

    with staging.open_timeseries(resolved_id, IngestProvenance.customer_measured.value) as writer:
        if file_format == "csv":
            _stream_csv(src, acc, tag_map, writer, file_timezone)
        else:
            _stream_parquet(src, acc, tag_map, writer, file_timezone, chunk_rows)
        writer.set_metadata(
            {
                "source_file": src.name,
                "file_format": file_format,
                "file_timezone": file_timezone,
                "tag_map_id": tag_map.map_id,
            }
        )
        staged = writer.artifact()

    warnings = [
        ParseWarning(code=code, message=_warning_message(code), detail={"row_count": count})
        for code, count in sorted(acc.warning_counts.items())
    ]
    unmapped = sorted(acc.unmapped_tags)

    summary: dict[str, Any] = {
        "file_format": file_format,
        "file_timezone": file_timezone,
        "total_rows": acc.total,
        "staged_rows": acc.staged,
        "unparsed_rows": acc.unparsed,
        "unmapped_tag_count": len(unmapped),
        "unmapped_tags": unmapped[:50],
        "tag_map_id": tag_map.map_id,
        "checksum_sha256": staged.checksum_sha256,
        # Explicit, machine-checkable safety statements:
        "promotes_to_calibrated": False,
        "analytic_labels_changed": False,
        "gap_filling": "none",
        "resampling": "none",
        "interpolation": "none",
    }

    proposal = ImportProposal(
        proposal_id=f"prop-{uuid.uuid4().hex[:12]}",
        kind=PROPOSAL_TIMESERIES_IMPORT,
        dataset_id=resolved_id,
        provenance=IngestProvenance.customer_measured.value,
        staged_artifact_id=staged.artifact_id,
        record_count=acc.staged,
        summary=summary,
    )

    return HistorianParseResult(
        dataset_id=resolved_id,
        file_format=file_format,
        provenance=IngestProvenance.customer_measured.value,
        file_timezone=file_timezone,
        staged=staged,
        proposal=proposal,
        total_rows=acc.total,
        staged_rows=acc.staged,
        unparsed_count=acc.unparsed,
        unparsed_sample=acc.unparsed_sample,
        unmapped_tags=unmapped,
        warnings=warnings,
    )


def _warning_message(code: str) -> str:
    return {
        "naive_timestamp_no_timezone": (
            "Naive timestamp with no per-row or file-level timezone; row not "
            "imported (UTC is never assumed on plant data)."
        ),
        "ambiguous_local_time": (
            "Local time is ambiguous (DST fold) under the declared timezone; "
            "row not imported."
        ),
        "nonexistent_local_time": (
            "Local time does not exist (DST gap) under the declared timezone; "
            "row not imported."
        ),
        "unknown_timezone": "Row timezone could not be resolved; row not imported.",
        "unparsable_timestamp": "Timestamp could not be parsed; row not imported.",
        "unmapped_tag": "Tag is not in the tag-mapping configuration; not guessed.",
        "missing_tag": "Row has no tag; row not imported.",
        "non_numeric_value": "Value is not numeric; row not imported.",
        "non_finite_value": "Value is not finite; row not imported.",
    }.get(code, code)
