"""Tests for the canonical S3M Operations Assistant models.

Lock the shape + safety defaults of the assistant/document models added to the
single canonical package: the control boundary defaults to read-only, an answer
always carries an evidence block, and a document reference is typed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from canonical_water_model import (
    AssistantQuery,
    AssistantResponse,
    ControlBoundary,
    DocumentRef,
    DocumentType,
    Evidence,
    now_iso,
)


def _evidence() -> Evidence:
    return Evidence(
        telemetry_window="live synthetic",
        assets_reviewed=["AST-HPP-01"],
        documents_reviewed=["MAN-HPP-001"],
        simulation_ids=[],
        assumptions=["advisory only"],
        data_timestamp=now_iso(),
    )


def test_document_ref_is_typed():
    ref = DocumentRef(
        document_id="MAN-HPP-001",
        title="HP Pump Manual",
        document_type=DocumentType.manual,
        path="data/manuals/hp_pump_manual.md",
        tags=["pump", "AST-HPP-01"],
        score=12.5,
        snippet="excerpt",
    )
    assert ref.document_type == DocumentType.manual
    assert ref.score == 12.5


def test_assistant_response_defaults_are_read_only_and_grounded():
    resp = AssistantResponse(
        query="Why is HPP-001 degrading?",
        intent="explain_degradation",
        target="AST-HPP-01",
        answer="Health is degraded; root cause is bearing wear.",
        evidence=_evidence(),
        confidence=0.8,
        source_engine_status="fallback_local",
    )
    # Read-only control boundary by default.
    assert resp.control_boundary == ControlBoundary()
    assert resp.control_boundary.control_write_enabled is False
    # Grounded + approval-required defaults.
    assert resp.grounded is True
    assert resp.approval_required is True
    # Evidence block is always present.
    assert resp.evidence.assets_reviewed == ["AST-HPP-01"]


def test_assistant_response_confidence_is_bounded():
    with pytest.raises(ValidationError):
        AssistantResponse(
            query="q",
            intent="unknown",
            answer="a",
            evidence=_evidence(),
            confidence=1.5,
            source_engine_status="fallback_local",
        )


def test_assistant_query_requires_a_question():
    with pytest.raises(ValidationError):
        AssistantQuery(question="")
