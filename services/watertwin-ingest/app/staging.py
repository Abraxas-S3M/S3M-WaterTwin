"""Staging store for bulk imports.

Imported files never stream straight into the analytic/telemetry store. They are
written to a **staging area** on disk and referenced by an approval proposal.
Only after an operator approves the proposal (a separate, human step, out of
scope for the parsers) would a downstream job load the staged artifact.

The store is intentionally simple and streaming: the time-series writer appends
one JSON object per line (NDJSON) as records are produced, so a 500 MB source
file is consumed in bounded memory -- we never hold the whole dataset in RAM.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

from canonical_water_model import now_iso

STAGED_TIMESERIES = "timeseries"
STAGED_GIS_LAYER = "gis_layer"


@dataclass(frozen=True)
class StagedArtifact:
    """A handle to a staged, not-yet-imported file living under the staging root."""

    artifact_id: str
    kind: str
    path: str
    provenance: str
    record_count: int
    checksum_sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "path": self.path,
            "provenance": self.provenance,
            "record_count": self.record_count,
            "checksum_sha256": self.checksum_sha256,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class StagedTimeSeriesWriter:
    """Streaming NDJSON writer for staged time-series records.

    Use as a context manager. Each :meth:`append` writes one line and updates a
    rolling SHA-256 and record count; nothing is buffered in memory beyond the
    current record. :meth:`artifact` returns the finalized handle after close.
    """

    def __init__(self, artifact_id: str, path: Path, provenance: str) -> None:
        self._artifact_id = artifact_id
        self._path = path
        self._provenance = provenance
        self._count = 0
        self._digest = hashlib.sha256()
        self._fh: Any = None
        self._metadata: dict[str, Any] = {}

    def __enter__(self) -> StagedTimeSeriesWriter:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("w", encoding="utf-8")
        return self

    def append(self, record: dict[str, Any]) -> None:
        if self._fh is None:  # pragma: no cover - misuse guard
            raise RuntimeError("writer is not open")
        line = json.dumps(record, separators=(",", ":"), sort_keys=True)
        self._digest.update(line.encode("utf-8"))
        self._digest.update(b"\n")
        self._fh.write(line)
        self._fh.write("\n")
        self._count += 1

    def set_metadata(self, metadata: dict[str, Any]) -> None:
        self._metadata = dict(metadata)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fh is not None:
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self._fh.close()
            self._fh = None

    @property
    def record_count(self) -> int:
        return self._count

    def artifact(self) -> StagedArtifact:
        return StagedArtifact(
            artifact_id=self._artifact_id,
            kind=STAGED_TIMESERIES,
            path=str(self._path),
            provenance=self._provenance,
            record_count=self._count,
            checksum_sha256=self._digest.hexdigest(),
            metadata=self._metadata,
        )


class StagingStore:
    """A filesystem-backed staging area under a single root directory."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def open_timeseries(self, dataset_id: str, provenance: str) -> StagedTimeSeriesWriter:
        """Open a streaming writer for a staged time-series dataset."""
        path = self._root / f"{dataset_id}.timeseries.ndjson"
        return StagedTimeSeriesWriter(dataset_id, path, provenance)

    def open_gis_layer(
        self,
        dataset_id: str,
        provenance: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> StagedGisLayerWriter:
        """Open a streaming writer for a staged GeoJSON ``FeatureCollection``."""
        path = self._root / f"{dataset_id}.geojson"
        return StagedGisLayerWriter(dataset_id, path, provenance, metadata or {})


class StagedGisLayerWriter:
    """Streaming writer that emits a GeoJSON ``FeatureCollection`` incrementally.

    Features are appended one at a time (never buffered as a whole list), so a
    large layer stages in bounded memory. A rolling SHA-256 covers the exact
    bytes written.
    """

    def __init__(
        self, artifact_id: str, path: Path, provenance: str, metadata: dict[str, Any]
    ) -> None:
        self._artifact_id = artifact_id
        self._path = path
        self._provenance = provenance
        self._metadata = dict(metadata)
        self._count = 0
        self._digest = hashlib.sha256()
        self._fh: Any = None
        self._first = True

    def _write(self, text: str) -> None:
        self._digest.update(text.encode("utf-8"))
        self._fh.write(text)

    def __enter__(self) -> StagedGisLayerWriter:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("w", encoding="utf-8")
        self._write('{"type":"FeatureCollection",')
        if self._metadata:
            self._write('"metadata":')
            self._write(json.dumps(self._metadata, separators=(",", ":"), sort_keys=True))
            self._write(",")
        self._write('"features":[')
        return self

    def append(self, feature: dict[str, Any]) -> None:
        if self._fh is None:  # pragma: no cover - misuse guard
            raise RuntimeError("writer is not open")
        prefix = "" if self._first else ","
        self._first = False
        self._write(prefix)
        self._write(json.dumps(feature, separators=(",", ":"), sort_keys=True))
        self._count += 1

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fh is not None:
            self._write("]}")
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self._fh.close()
            self._fh = None

    @property
    def record_count(self) -> int:
        return self._count

    def artifact(self) -> StagedArtifact:
        return StagedArtifact(
            artifact_id=self._artifact_id,
            kind=STAGED_GIS_LAYER,
            path=str(self._path),
            provenance=self._provenance,
            record_count=self._count,
            checksum_sha256=self._digest.hexdigest(),
            metadata=self._metadata,
        )
