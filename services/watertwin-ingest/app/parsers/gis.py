"""Geospatial layer parser (``.geojson`` / zipped shapefile).

Safety-relevant behaviour (all enforced by tests):

* **XML is parsed with :mod:`defusedxml`** with DTDs / entities forbidden, so a
  GeoJSON (or sidecar) carrying an external-entity payload is rejected.
* **Archive members are path-sanitized** (Phase B checks reused): a shapefile
  zip containing a ``..`` traversal (or absolute) member is rejected wholesale.
* **CRS handling is explicit**: the source CRS is taken from an explicit
  argument, the GeoJSON ``crs`` member, or the shapefile ``.prj``; geometry is
  reprojected to the platform CRS and *both* CRSs are recorded. If the source
  CRS cannot be determined, the import fails loudly.
* **Geometry is validated before staging** (via
  :func:`network_twin.validate_geometry`); invalid geometry is reported, never
  silently repaired.
* **Provenance is ``customer_supplied``**; the parser writes to staging and
  emits an approval proposal only.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyproj
import shapefile
from network_twin import validate_geometry

from ..proposals import PROPOSAL_GIS_LAYER_IMPORT, ImportProposal
from ..provenance import PLATFORM_CRS, IngestProvenance
from ..security import (
    looks_like_xml,
    safe_parse_xml,
    sanitize_archive_member,
)
from ..staging import StagedArtifact, StagingStore
from .base import ParseWarning, UnparsedRecord

MAX_INVALID_SAMPLE = 1_000
_SHAPEFILE_EXTS = (".shp", ".dbf", ".shx", ".prj")


class GisParseError(ValueError):
    """Raised for unrecoverable GIS-import problems (bad format, unknown CRS)."""


@dataclass
class GisParseResult:
    """Outcome of a GIS import: the staged layer, proposal, and reports."""

    dataset_id: str
    layer_format: str
    provenance: str
    source_crs: str
    target_crs: str
    staged: StagedArtifact
    proposal: ImportProposal
    total_features: int
    staged_features: int
    invalid_count: int
    invalid_sample: list[UnparsedRecord] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)


def _crs_string(crs: pyproj.CRS) -> str:
    authority = crs.to_authority()
    if authority is not None:
        return f"{authority[0]}:{authority[1]}"
    return crs.to_string()


def _looks_like_position(coords: Any) -> bool:
    return (
        isinstance(coords, list | tuple)
        and len(coords) >= 2
        and isinstance(coords[0], int | float)
        and not isinstance(coords[0], bool)
        and isinstance(coords[1], int | float)
        and not isinstance(coords[1], bool)
    )


def _reproject_coords(coords: Any, transform: pyproj.Transformer) -> Any:
    if _looks_like_position(coords):
        x, y = transform.transform(coords[0], coords[1])
        return [round(float(x), 7), round(float(y), 7), *list(coords[2:])]
    if isinstance(coords, list | tuple):
        return [_reproject_coords(c, transform) for c in coords]
    raise GisParseError("malformed coordinate array")


def _reproject_geometry(geometry: Any, transform: pyproj.Transformer) -> dict[str, Any]:
    if not isinstance(geometry, dict) or "coordinates" not in geometry:
        raise GisParseError("geometry has no coordinates")
    return {
        "type": geometry.get("type"),
        "coordinates": _reproject_coords(geometry["coordinates"], transform),
    }


class _GisAccumulator:
    def __init__(self) -> None:
        self.total = 0
        self.staged = 0
        self.invalid = 0
        self.invalid_sample: list[UnparsedRecord] = []

    def reject(self, reason: str, location: str, raw: dict[str, Any]) -> None:
        self.invalid += 1
        if len(self.invalid_sample) < MAX_INVALID_SAMPLE:
            self.invalid_sample.append(UnparsedRecord(reason, location, raw))


def _stage_feature(
    acc: _GisAccumulator,
    writer: Any,
    geometry: Any,
    properties: dict[str, Any],
    transform: pyproj.Transformer,
    location: str,
) -> None:
    """Reproject, validate, and stage one feature; report if invalid."""
    acc.total += 1
    if geometry is None:
        acc.reject("null_geometry", location, {})
        return
    try:
        reprojected = _reproject_geometry(geometry, transform)
    except (GisParseError, ValueError, TypeError) as exc:
        acc.reject("reprojection_failed", location, {"error": str(exc)})
        return

    validation = validate_geometry(reprojected)
    if not validation.valid:
        acc.reject("invalid_geometry", location, {"reasons": validation.reasons})
        return

    writer.append(
        {
            "type": "Feature",
            "geometry": reprojected,
            "properties": {**properties, "_provenance": IngestProvenance.customer_supplied.value},
        }
    )
    acc.staged += 1


def _geojson_source_crs(doc: dict[str, Any], override: str | None) -> str:
    if override:
        return override
    crs = doc.get("crs")
    if isinstance(crs, dict):
        props = crs.get("properties")
        name = props.get("name") if isinstance(props, dict) else None
        if isinstance(name, str) and name.strip():
            return name.strip()
    # RFC 7946 defines GeoJSON coordinates as WGS84 lon/lat when no CRS is given.
    return PLATFORM_CRS


def _parse_geojson(
    src: Path,
    acc: _GisAccumulator,
    writer_factory: Any,
    source_crs_override: str | None,
    target_crs: str,
) -> tuple[str, str]:
    raw = src.read_bytes()
    if looks_like_xml(raw[:512]):
        # Force it through the hardened XML parser so a DTD/entity is rejected.
        safe_parse_xml(raw)
        raise GisParseError("GeoJSON payload contains XML; rejected")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GisParseError(f"invalid GeoJSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise GisParseError("GeoJSON root must be an object")

    source_crs_name = _geojson_source_crs(doc, source_crs_override)
    src_crs = pyproj.CRS.from_user_input(source_crs_name)
    tgt_crs = pyproj.CRS.from_user_input(target_crs)
    transform = pyproj.Transformer.from_crs(src_crs, tgt_crs, always_xy=True)

    if doc.get("type") == "FeatureCollection":
        features = doc.get("features") or []
    elif doc.get("type") == "Feature":
        features = [doc]
    else:
        features = [{"type": "Feature", "geometry": doc, "properties": {}}]

    for i, feature in enumerate(features):
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        props = feature.get("properties") if isinstance(feature, dict) else None
        _stage_feature(
            acc,
            writer_factory,
            geometry,
            props if isinstance(props, dict) else {},
            transform,
            location=f"feature {i}",
        )
    return _crs_string(src_crs), _crs_string(tgt_crs)


def _extract_shapefile(zf: zipfile.ZipFile, dest: Path) -> dict[str, Path]:
    """Sanitize every member, then extract the shapefile component set to ``dest``."""
    names = [n for n in zf.namelist() if not n.endswith("/")]
    for name in names:
        # Reject the whole archive on ANY unsafe member (do not silently skip).
        sanitize_archive_member(name)

    shp_members = [n for n in names if n.lower().endswith(".shp")]
    if not shp_members:
        raise GisParseError("archive contains no .shp member")
    shp_name = shp_members[0]
    stem = Path(sanitize_archive_member(shp_name)).stem.lower()

    components: dict[str, Path] = {}
    for name in names:
        safe = sanitize_archive_member(name)
        p = Path(safe)
        ext = p.suffix.lower()
        if ext in _SHAPEFILE_EXTS and p.stem.lower() == stem:
            out_path = dest / f"{stem}{ext}"
            with zf.open(name) as member_fh, out_path.open("wb") as out_fh:
                shutil.copyfileobj(member_fh, out_fh, length=1024 * 1024)
            components[ext] = out_path
    if ".shp" not in components or ".dbf" not in components:
        raise GisParseError("archive is missing required .shp/.dbf shapefile components")
    return components


def _shapefile_source_crs(components: dict[str, Path], override: str | None) -> str:
    if override:
        return override
    prj = components.get(".prj")
    if prj is None:
        raise GisParseError(
            "shapefile has no .prj and no source CRS was provided; CRS must be explicit"
        )
    wkt = prj.read_text(encoding="utf-8", errors="strict").strip()
    if not wkt:
        raise GisParseError("shapefile .prj is empty; CRS must be explicit")
    return wkt


def _parse_shapefile_zip(
    src: Path,
    acc: _GisAccumulator,
    writer: Any,
    source_crs_override: str | None,
    target_crs: str,
) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="watertwin-shp-") as tmp:
        with zipfile.ZipFile(src) as zf:
            components = _extract_shapefile(zf, Path(tmp))

        source_crs_name = _shapefile_source_crs(components, source_crs_override)
        src_crs = pyproj.CRS.from_user_input(source_crs_name)
        tgt_crs = pyproj.CRS.from_user_input(target_crs)
        transform = pyproj.Transformer.from_crs(src_crs, tgt_crs, always_xy=True)

        reader = shapefile.Reader(str(components[".shp"]))
        try:
            for i, shape_record in enumerate(reader.iterShapeRecords()):
                shape = shape_record.shape
                geometry = None if shape.shapeType == shapefile.NULL else shape.__geo_interface__
                props = dict(shape_record.record.as_dict())
                _stage_feature(acc, writer, geometry, props, transform, location=f"shape {i}")
        finally:
            reader.close()
    return _crs_string(src_crs), _crs_string(tgt_crs)


def parse_gis(
    path: str | Path,
    *,
    staging: StagingStore,
    source_crs: str | None = None,
    target_crs: str = PLATFORM_CRS,
    dataset_id: str | None = None,
) -> GisParseResult:
    """Parse a GeoJSON or zipped shapefile into staging and build a proposal.

    ``source_crs`` (any pyproj-accepted spec) overrides an in-file CRS. Geometry
    is reprojected to ``target_crs`` (the platform CRS by default) and both CRSs
    are recorded on the staged artifact and the proposal.
    """
    src = Path(path)
    suffix = src.suffix.lower()
    if suffix in (".geojson", ".json"):
        layer_format = "geojson"
    elif suffix == ".zip":
        layer_format = "shapefile"
    else:
        raise GisParseError(f"unsupported GIS format: {src.suffix!r}")

    resolved_id = dataset_id or f"{src.stem or 'gis'}-{uuid.uuid4().hex[:8]}"
    acc = _GisAccumulator()

    provenance = IngestProvenance.customer_supplied.value
    writer_meta: dict[str, Any] = {
        "source_file": src.name,
        "layer_format": layer_format,
        "target_crs": target_crs,
    }
    with staging.open_gis_layer(resolved_id, provenance, metadata=writer_meta) as writer:
        if layer_format == "geojson":
            source_crs_str, target_crs_str = _parse_geojson(
                src, acc, writer, source_crs, target_crs
            )
        else:
            source_crs_str, target_crs_str = _parse_shapefile_zip(
                src, acc, writer, source_crs, target_crs
            )
        staged = writer.artifact()

    # Rewrite the staged metadata record with the resolved CRSs for provenance.
    staged = StagedArtifact(
        artifact_id=staged.artifact_id,
        kind=staged.kind,
        path=staged.path,
        provenance=staged.provenance,
        record_count=staged.record_count,
        checksum_sha256=staged.checksum_sha256,
        metadata={**staged.metadata, "source_crs": source_crs_str, "target_crs": target_crs_str},
    )

    warnings: list[ParseWarning] = []
    if acc.invalid:
        warnings.append(
            ParseWarning(
                code="invalid_geometry",
                message="Some geometries were invalid and were reported, not repaired.",
                detail={"count": acc.invalid},
            )
        )

    summary: dict[str, Any] = {
        "layer_format": layer_format,
        "source_crs": source_crs_str,
        "target_crs": target_crs_str,
        "total_features": acc.total,
        "staged_features": acc.staged,
        "invalid_features": acc.invalid,
        "checksum_sha256": staged.checksum_sha256,
        "promotes_to_calibrated": False,
        "analytic_labels_changed": False,
    }

    proposal = ImportProposal(
        proposal_id=f"prop-{uuid.uuid4().hex[:12]}",
        kind=PROPOSAL_GIS_LAYER_IMPORT,
        dataset_id=resolved_id,
        provenance=provenance,
        staged_artifact_id=staged.artifact_id,
        record_count=acc.staged,
        summary=summary,
    )

    return GisParseResult(
        dataset_id=resolved_id,
        layer_format=layer_format,
        provenance=provenance,
        source_crs=source_crs_str,
        target_crs=target_crs_str,
        staged=staged,
        proposal=proposal,
        total_features=acc.total,
        staged_features=acc.staged,
        invalid_count=acc.invalid,
        invalid_sample=acc.invalid_sample,
        warnings=warnings,
    )
