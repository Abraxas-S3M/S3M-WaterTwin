"""Tests for network_twin.gis_validation (report, never repair)."""

from __future__ import annotations

from network_twin import GeometryValidation, validate_geometry


def test_valid_point() -> None:
    result = validate_geometry({"type": "Point", "coordinates": [55.0, 25.0]})
    assert isinstance(result, GeometryValidation)
    assert result.valid is True
    assert result.reasons == []


def test_valid_linestring_and_polygon() -> None:
    line = validate_geometry(
        {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]]}
    )
    assert line.valid is True
    square = validate_geometry(
        {
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]],
        }
    )
    assert square.valid is True


def test_unsupported_type_is_invalid() -> None:
    result = validate_geometry({"type": "Circle", "coordinates": [0, 0]})
    assert result.valid is False
    assert any("unsupported" in r for r in result.reasons)


def test_non_finite_coordinates_are_invalid() -> None:
    result = validate_geometry({"type": "Point", "coordinates": [float("nan"), 25.0]})
    assert result.valid is False
    assert any("non-finite" in r for r in result.reasons)


def test_unclosed_ring_is_invalid() -> None:
    result = validate_geometry(
        {"type": "Polygon", "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0]]]}
    )
    assert result.valid is False
    assert any("at least 4 positions" in r or "not closed" in r for r in result.reasons)


def test_self_intersecting_ring_is_invalid_not_repaired() -> None:
    bowtie = [[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]
    result = validate_geometry({"type": "Polygon", "coordinates": [bowtie]})
    assert result.valid is False
    assert any("self-intersecting" in r for r in result.reasons)


def test_degenerate_linestring_is_invalid() -> None:
    result = validate_geometry(
        {"type": "LineString", "coordinates": [[1.0, 1.0], [1.0, 1.0]]}
    )
    assert result.valid is False


def test_multipolygon_validates_each_part() -> None:
    good_ring = [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]
    bad_ring = [[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]
    result = validate_geometry(
        {"type": "MultiPolygon", "coordinates": [[good_ring], [bad_ring]]}
    )
    assert result.valid is False
