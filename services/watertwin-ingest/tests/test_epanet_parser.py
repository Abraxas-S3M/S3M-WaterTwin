"""Tests for the EPANET 2.2 ``.inp`` parser and the content/XXE guard."""

from __future__ import annotations

import os

import pytest

from app.parsers import (
    UnsafeContentError,
    get_parser,
    guard_unsafe_content,
    sniff_format,
)
from app.parsers.base import ParseScope, ParseStatus

from .conftest import DEMO_INP

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _fixture(name: str) -> str:
    return os.path.join(FIXTURES, name)


def _parse(path: str, sections: list[str] | None = None):
    parser = get_parser("epanet")
    scope = ParseScope(file_format="epanet", sections=sections or [])
    return parser.parse(path, scope)


def test_small_valid_network_exact_entity_counts():
    result = _parse(_fixture("small_valid.inp"))
    assert result.status is ParseStatus.parsed
    assert result.entity_counts() == {
        "junction": 3,
        "reservoir": 1,
        "tank": 1,
        "pipe": 4,
        "pump": 1,
        "valve": 1,
        "curve": 1,
        "pattern": 1,
    }
    assert not result.unparsed


def test_demo_network_round_trips_exact_counts():
    result = _parse(DEMO_INP)
    assert result.status is ParseStatus.parsed
    counts = result.entity_counts()
    assert counts["junction"] == 6
    assert counts["reservoir"] == 1
    assert counts["tank"] == 1
    assert counts["pipe"] == 5
    assert counts["pump"] == 2
    assert counts["valve"] == 1
    assert result.stats.source_units == "CMH"


def test_every_entity_records_a_source_line():
    result = _parse(_fixture("small_valid.inp"))
    assert result.entities
    for entity in result.entities:
        assert entity.source_line >= 1
        assert entity.provenance == "customer_supplied"


def test_units_are_normalized_to_canonical_si():
    # small_valid.inp is in LPS; base demand 5 L/s -> 18 m3/h, 10 L/s -> 36 m3/h.
    result = _parse(_fixture("small_valid.inp"))
    j1 = next(e for e in result.entities if e.entity_id == "J1")
    assert j1.fields["elevation_m"] == pytest.approx(100.0)
    assert j1.fields["base_demand_m3h"] == pytest.approx(18.0)
    j2 = next(e for e in result.entities if e.entity_id == "J2")
    assert j2.fields["base_demand_m3h"] == pytest.approx(36.0)


def test_missing_units_warns_and_routes_fields_to_unparsed():
    result = _parse(_fixture("missing_units.inp"))
    assert result.status is ParseStatus.partial
    assert any("UNITS is absent" in w.message for w in result.warnings)
    # The hydraulic fields must not be guessed: they land in `unparsed`.
    assert result.unparsed
    unparsed_fields = {u.field for u in result.unparsed}
    assert "elevation_m" in unparsed_fields
    assert "length_m" in unparsed_fields
    # Non-unit fields (ids, node refs) still parse.
    p1 = next(e for e in result.entities if e.entity_id == "P1")
    assert p1.fields["node1"] == "R1"
    assert "length_m" not in p1.fields


def test_unknown_section_is_a_warning_not_a_drop_or_crash():
    result = _parse(_fixture("unknown_section.inp"))
    assert result.status in {ParseStatus.parsed, ParseStatus.partial}
    assert any("WIDGETS" in w.message for w in result.warnings)
    # The known sections still parse normally around the unknown one.
    assert result.entity_counts()["junction"] == 2
    assert result.entity_counts()["pipe"] == 1


def test_truncated_mid_section_is_partial_without_exception():
    result = _parse(_fixture("truncated.inp"))
    assert result.status is ParseStatus.partial
    # P1 parsed fully; P2 is truncated -> its missing end node is unparsed.
    assert any(e.entity_id == "P1" for e in result.entities)
    assert any(u.entity_id == "P2" and u.field == "node2" for u in result.unparsed)


def test_scope_can_restrict_extracted_sections():
    result = _parse(_fixture("small_valid.inp"), sections=["JUNCTIONS"])
    counts = result.entity_counts()
    assert counts == {"junction": 3}


def test_fifty_thousand_line_network_completes(tmp_path):
    n = 17000
    lines = ["[OPTIONS]", "UNITS CMH", "HEADLOSS H-W", "", "[JUNCTIONS]"]
    for i in range(n):
        lines.append(f" J{i}  100  5")
    lines.append("[PIPES]")
    for i in range(n - 1):
        lines.append(f" P{i}  J{i}  J{i + 1}  100  200  130  0  Open")
    lines.append("[COORDINATES]")
    for i in range(n):
        lines.append(f" J{i}  {i}  0")
    path = tmp_path / "big.inp"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert len(lines) >= 50_000

    result = _parse(str(path))
    assert result.status is ParseStatus.parsed
    assert result.entity_counts()["junction"] == n
    assert result.entity_counts()["pipe"] == n - 1
    # The plain-text parser is fast; a generous ceiling guards against regressions.
    assert result.stats.duration_s < 20.0


def test_xxe_external_entity_is_rejected():
    with open(_fixture("xxe.inp"), "rb") as handle:
        raw = handle.read()
    with pytest.raises(UnsafeContentError):
        guard_unsafe_content(raw)


def test_plain_inp_passes_the_content_guard():
    with open(DEMO_INP, "rb") as handle:
        raw = handle.read()
    # A normal EPANET .inp is not XML and must pass the guard untouched.
    guard_unsafe_content(raw)
    assert sniff_format(raw) == "epanet"


def test_parser_never_raises_on_binary_garbage(tmp_path):
    path = tmp_path / "garbage.inp"
    path.write_bytes(bytes(range(256)) * 32)
    result = _parse(str(path))
    # Never an exception: it returns whatever (little) it could make sense of.
    assert result.status in {ParseStatus.parsed, ParseStatus.partial}
