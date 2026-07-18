"""Tests for the geospatial layer parser (GeoJSON + zipped shapefile)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pyproj
import pytest
import shapefile

from app.parsers.gis import GisParseError, parse_gis
from app.provenance import IngestProvenance
from app.security import UnsafeArchiveMemberError, UnsafeXmlError
from app.staging import StagingStore

# A point in Web Mercator (EPSG:3857) with a known WGS84 image (~lon 55.0, lat 25.1).
MERC_X, MERC_Y = 6124092.0, 2887060.0
EXPECTED_LON, EXPECTED_LAT = 55.01365, 25.09209


def _staged_features(path: str) -> list[dict]:
    doc = json.loads(Path(path).read_text())
    return doc["features"]


def _write_point_shapefile_zip(zip_path: Path, tmp: Path, epsg: int, x: float, y: float) -> None:
    base = tmp / "layer"
    writer = shapefile.Writer(str(base))
    writer.field("name", "C")
    writer.point(x, y)
    writer.record("HPP-01")
    writer.close()
    (tmp / "layer.prj").write_text(pyproj.CRS.from_epsg(epsg).to_wkt(), encoding="utf-8")
    with zipfile.ZipFile(zip_path, "w") as zf:
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            zf.write(tmp / f"layer{ext}", arcname=f"layer{ext}")


def test_geojson_reprojected_and_both_crs_recorded(
    tmp_path: Path, staging: StagingStore
) -> None:
    doc = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3857"}},
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [MERC_X, MERC_Y]},
                "properties": {"name": "HPP-01"},
            }
        ],
    }
    path = tmp_path / "layer.geojson"
    path.write_text(json.dumps(doc), encoding="utf-8")

    result = parse_gis(path, staging=staging)

    assert result.provenance == IngestProvenance.customer_supplied.value
    assert result.source_crs == "EPSG:3857"
    assert result.target_crs == "EPSG:4326"
    assert result.staged.metadata["source_crs"] == "EPSG:3857"
    assert result.staged.metadata["target_crs"] == "EPSG:4326"
    assert result.staged_features == 1

    coords = _staged_features(result.staged.path)[0]["geometry"]["coordinates"]
    assert coords[0] == pytest.approx(EXPECTED_LON, abs=1e-4)
    assert coords[1] == pytest.approx(EXPECTED_LAT, abs=1e-4)


def test_geojson_without_crs_defaults_to_wgs84_and_is_identity(
    tmp_path: Path, staging: StagingStore
) -> None:
    doc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [55.1, 25.2]},
                "properties": {},
            }
        ],
    }
    path = tmp_path / "wgs84.geojson"
    path.write_text(json.dumps(doc), encoding="utf-8")

    result = parse_gis(path, staging=staging)

    assert result.source_crs == "EPSG:4326"
    assert result.target_crs == "EPSG:4326"
    coords = _staged_features(result.staged.path)[0]["geometry"]["coordinates"]
    assert coords[0] == pytest.approx(55.1)
    assert coords[1] == pytest.approx(25.2)


def test_geojson_xxe_attempt_is_rejected(tmp_path: Path, staging: StagingStore) -> None:
    payload = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE root [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
        "<root>&xxe;</root>\n"
    )
    path = tmp_path / "evil.geojson"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises((UnsafeXmlError, GisParseError)):
        parse_gis(path, staging=staging)


def test_invalid_geometry_is_reported_not_repaired(
    tmp_path: Path, staging: StagingStore
) -> None:
    # A self-intersecting "bow-tie" polygon ring (invalid, must not be repaired).
    bowtie = [[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]
    doc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [55.0, 25.0]},
                "properties": {"name": "ok"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [bowtie]},
                "properties": {"name": "bad"},
            },
        ],
    }
    path = tmp_path / "mixed.geojson"
    path.write_text(json.dumps(doc), encoding="utf-8")

    result = parse_gis(path, staging=staging)

    assert result.total_features == 2
    assert result.staged_features == 1
    assert result.invalid_count == 1
    assert result.invalid_sample[0].reason == "invalid_geometry"
    # The invalid geometry is reported with a reason, never staged/repaired.
    staged = _staged_features(result.staged.path)
    assert len(staged) == 1
    assert staged[0]["properties"]["name"] == "ok"
    assert any("self-intersecting" in r for r in result.invalid_sample[0].raw["reasons"])


def test_shapefile_zip_imports_with_crs_reprojection(
    tmp_path: Path, staging: StagingStore
) -> None:
    zip_path = tmp_path / "network.zip"
    _write_point_shapefile_zip(zip_path, tmp_path, epsg=3857, x=MERC_X, y=MERC_Y)

    result = parse_gis(zip_path, staging=staging)

    assert result.layer_format == "shapefile"
    assert result.provenance == IngestProvenance.customer_supplied.value
    assert result.source_crs == "EPSG:3857"
    assert result.target_crs == "EPSG:4326"
    assert result.staged_features == 1

    feature = _staged_features(result.staged.path)[0]
    assert feature["properties"]["name"] == "HPP-01"
    assert feature["properties"]["_provenance"] == "customer_supplied"
    coords = feature["geometry"]["coordinates"]
    assert coords[0] == pytest.approx(EXPECTED_LON, abs=1e-4)
    assert coords[1] == pytest.approx(EXPECTED_LAT, abs=1e-4)


def test_shapefile_zip_with_traversal_member_is_rejected(
    tmp_path: Path, staging: StagingStore
) -> None:
    zip_path = tmp_path / "evil.zip"
    inner = tmp_path / "inner"
    inner.mkdir()
    _write_point_shapefile_zip(tmp_path / "good.zip", inner, epsg=4326, x=55.0, y=25.0)
    with zipfile.ZipFile(tmp_path / "good.zip") as good, zipfile.ZipFile(zip_path, "w") as zf:
        for name in good.namelist():
            zf.writestr(name, good.read(name))
        # Add a malicious traversal member.
        zf.writestr("../../etc/evil.shp", b"malicious")

    with pytest.raises(UnsafeArchiveMemberError):
        parse_gis(zip_path, staging=staging)


def test_shapefile_zip_without_prj_requires_explicit_crs(
    tmp_path: Path, staging: StagingStore
) -> None:
    base = tmp_path / "layer"
    writer = shapefile.Writer(str(base))
    writer.field("name", "C")
    writer.point(55.0, 25.0)
    writer.record("A")
    writer.close()
    zip_path = tmp_path / "noprj.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for ext in (".shp", ".shx", ".dbf"):
            zf.write(tmp_path / f"layer{ext}", arcname=f"layer{ext}")

    # No .prj and no explicit CRS -> loud failure (CRS must be explicit).
    with pytest.raises(GisParseError):
        parse_gis(zip_path, staging=staging)

    # Providing the CRS explicitly makes it import.
    result = parse_gis(zip_path, staging=staging, source_crs="EPSG:4326")
    assert result.source_crs == "EPSG:4326"
    assert result.staged_features == 1
