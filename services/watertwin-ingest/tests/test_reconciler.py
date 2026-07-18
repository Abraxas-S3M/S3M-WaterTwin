"""Tests for the reconciler, the canonical HTTP client, and the proposal builder."""

from __future__ import annotations

from typing import Any

from app.parsers import get_parser
from app.parsers.base import ParsedEntity, ParseResult, ParseScope, ParseStatus
from app.proposal import build_proposal
from app.reconciler import (
    CanonicalConfigClient,
    CanonicalRecord,
    FieldClassification,
    MatchType,
    reconcile,
)

from .conftest import DEMO_INP

_NETWORK_TYPES = {"junction", "reservoir", "tank", "pipe", "pump", "valve"}
THRESHOLD = 0.82


# --- fakes for the injectable HTTP session (mirrors the hydraulic-client pattern) ---


class _FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload


class _FakeSession:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self._status_code = status_code
        self.calls: list[str] = []

    def get(self, path: str) -> _FakeResponse:
        self.calls.append(path)
        return _FakeResponse(self._payload, self._status_code)


def _result(*entities: ParsedEntity) -> ParseResult:
    return ParseResult(status=ParseStatus.parsed, parser="test", entities=list(entities))


def _parse_demo() -> ParseResult:
    return get_parser("epanet").parse(DEMO_INP, ParseScope(file_format="epanet"))


def _features_from_parse(result: ParseResult) -> dict[str, Any]:
    features = []
    for entity in result.entities:
        if entity.entity_type not in _NETWORK_TYPES:
            continue
        props = {
            "element_id": entity.entity_id,
            "element_type": entity.entity_type,
            **entity.fields,
        }
        features.append({"type": "Feature", "id": entity.entity_id, "properties": props})
    return {"type": "FeatureCollection", "features": features}


# --- matching --------------------------------------------------------------


def test_exact_match_on_asset_id():
    parsed = _result(
        ParsedEntity(
            entity_type="junction", entity_id="J1", name="J1",
            fields={"elevation_m": 100.0}, source_line=5,
        )
    )
    canonical = [CanonicalRecord(record_id="J1", name="J1", entity_type="junction",
                                 fields={"elevation_m": 100.0})]
    out = reconcile(parsed, canonical, match_threshold=THRESHOLD)
    assert out.matched_count == 1 and out.new_count == 0
    entity = out.entities[0]
    assert entity.match_type is MatchType.exact
    assert entity.match_confidence == 1.0
    assert entity.field_diffs[0].classification is FieldClassification.unchanged


def test_fuzzy_match_above_threshold():
    parsed = _result(
        ParsedEntity(
            entity_type="pump", entity_id="PMP-STN-01", name="Booster Pump 1",
            fields={"power_kw": 75.0}, source_line=9,
        )
    )
    canonical = [
        CanonicalRecord(record_id="AST-BOOST-01", name="Booster Pump 01",
                        entity_type="pump", fields={"power_kw": 75.0}),
    ]
    out = reconcile(parsed, canonical, match_threshold=THRESHOLD)
    entity = out.entities[0]
    assert entity.match_type is MatchType.fuzzy
    assert entity.is_new is False
    assert THRESHOLD <= entity.match_confidence < 1.0
    assert entity.matched_record_id == "AST-BOOST-01"


def test_fuzzy_below_threshold_is_proposed_new():
    parsed = _result(
        ParsedEntity(
            entity_type="valve", entity_id="V-NEW-9", name="Emergency Isolation Valve",
            fields={"setting": 0.0}, source_line=11,
        )
    )
    canonical = [
        CanonicalRecord(record_id="CV-1", name="Chlorine Dosing Skid",
                        entity_type="valve", fields={"setting": 1.0}),
    ]
    out = reconcile(parsed, canonical, match_threshold=THRESHOLD)
    entity = out.entities[0]
    assert entity.is_new is True
    assert entity.match_type is MatchType.none
    assert entity.match_confidence < THRESHOLD
    assert all(d.classification is FieldClassification.new for d in entity.field_diffs)


def test_conflict_is_reported_not_auto_resolved():
    parsed = _result(
        ParsedEntity(
            entity_type="pipe", entity_id="P1", name="P1",
            fields={"length_m": 500.0, "diameter_mm": 300.0, "roughness": 120.0},
            source_line=14,
        )
    )
    canonical = [
        CanonicalRecord(record_id="P1", name="P1", entity_type="pipe",
                        fields={"length_m": 500.0, "diameter_mm": 250.0}),
    ]
    out = reconcile(parsed, canonical, match_threshold=THRESHOLD)
    entity = out.entities[0]
    assert entity.conflict is True
    assert out.conflict_count == 1
    classes = {d.field: d.classification for d in entity.field_diffs}
    assert classes["length_m"] is FieldClassification.unchanged
    assert classes["diameter_mm"] is FieldClassification.changed  # conflict
    assert classes["roughness"] is FieldClassification.new
    # A conflict carries BOTH values; it is never auto-resolved.
    changed = next(d for d in entity.field_diffs if d.field == "diameter_mm")
    assert changed.current_value == 250.0 and changed.proposed_value == 300.0


def test_non_network_types_are_skipped_not_proposed():
    parsed = _result(
        ParsedEntity(entity_type="curve", entity_id="C1", name="C1",
                     fields={"points": [[0, 60]]}, source_line=3),
        ParsedEntity(entity_type="junction", entity_id="J1", name="J1",
                     fields={"elevation_m": 1.0}, source_line=4),
    )
    canonical = [CanonicalRecord(record_id="J1", name="J1", entity_type="junction",
                                 fields={"elevation_m": 1.0})]
    out = reconcile(parsed, canonical, match_threshold=THRESHOLD)
    assert out.skipped_types == {"curve": 1}
    assert len(out.entities) == 1


# --- canonical HTTP client -------------------------------------------------


def test_canonical_client_fetches_and_adapts_features():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "id": "J1", "properties": {
                "element_id": "J1", "element_type": "junction",
                "canonical_asset_id": "J1", "elevation": 100.0, "base_demand": 5.0}},
            {"type": "Feature", "id": "P1", "properties": {
                "element_id": "P1", "element_type": "pipe",
                "start_node": "J1", "end_node": "J2", "length": 500.0, "diameter": 300.0}},
        ],
    }
    session = _FakeSession(payload)
    client = CanonicalConfigClient(session=session)
    records = client.fetch_records()
    assert session.calls == ["/api/v1/network/features"]
    by_id = {r.record_id: r for r in records}
    assert by_id["J1"].fields == {"elevation_m": 100.0, "base_demand_m3h": 5.0}
    assert by_id["P1"].fields["length_m"] == 500.0
    assert by_id["P1"].fields["diameter_mm"] == 300.0
    assert by_id["P1"].fields["node1"] == "J1"


# --- proposal --------------------------------------------------------------


def test_proposal_changes_are_advisory_and_traceable():
    parsed = _result(
        ParsedEntity(entity_type="pipe", entity_id="P1", name="P1",
                     fields={"diameter_mm": 300.0}, source_line=14),
        ParsedEntity(entity_type="pump", entity_id="PU-NEW", name="Brand New Pump",
                     fields={"power_kw": 50.0}, source_line=20),
    )
    canonical = [CanonicalRecord(record_id="P1", name="P1", entity_type="pipe",
                                 fields={"diameter_mm": 250.0})]
    out = reconcile(parsed, canonical, match_threshold=THRESHOLD)
    proposal = build_proposal(out, parsed, source_file="network.inp", upload_id="u1")

    assert proposal.changes, "expected proposed changes for a conflict + a new entity"
    for change in proposal.changes:
        assert change.accepted is False
        assert change.ai_suggested is False
        assert change.ai_confidence is None
        assert change.ai_rationale is None
        assert change.provenance == "customer_supplied"
        assert change.source_ref.startswith("network.inp:line ")
    # The conflicting field carries current + proposed and a conflict flag.
    conflict = next(c for c in proposal.changes if c.field == "diameter_mm")
    assert conflict.conflict is True
    assert conflict.source_ref == "network.inp:line 14"
    # Read-only control boundary is stamped on the proposal.
    assert proposal.control_boundary.control_write_enabled is False
    assert proposal.control_boundary.operator_approval_required is True


def test_demo_network_proposal_entity_counts_match_seeded_facility():
    parsed = _parse_demo()
    session = _FakeSession(_features_from_parse(parsed))
    client = CanonicalConfigClient(session=session)
    canonical = client.fetch_records()

    out = reconcile(parsed, canonical, match_threshold=THRESHOLD)
    # The demo round-trips: every network entity matches its seeded record.
    assert out.matched_count == 16
    assert out.new_count == 0
    assert out.conflict_count == 0

    proposal = build_proposal(out, parsed, source_file="ro-handoff.inp")
    assert proposal.entity_counts == {
        "junction": 6,
        "reservoir": 1,
        "tank": 1,
        "pipe": 5,
        "pump": 2,
        "valve": 1,
    }
    # Round-trip -> no field-level changes to propose.
    assert proposal.changes == []
    assert proposal.provenance == "customer_supplied"
