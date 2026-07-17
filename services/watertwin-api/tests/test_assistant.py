"""Tests for the S3M Operations Assistant + seeded document store.

Fast and dependency-free (no live hydraulic-sim). They cover:

* intent classification for every canonical example question;
* grounded aggregation for "why is HPP-001 degrading" (health + root-cause
  context, non-empty evidence);
* the S3M-Core-unreachable local fallback (``source_engine_status =
  "fallback_local"`` with evidence populated);
* the control boundary + full evidence block on every response, and that any
  recommended action is ``pending`` with control write disabled;
* the explicit "insufficient data" answer (never fabricated); and
* the seeded document endpoints + keyword retrieval.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import assistant, documents
from app.main import app
from app.s3m_connector import FALLBACK_LOCAL, ConnectorResult, S3mConnector


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        yield c


# --- Intent classification --------------------------------------------------


@pytest.mark.parametrize("example", assistant.EXAMPLE_QUESTIONS, ids=lambda e: e["intent"])
def test_classify_intent_maps_each_canonical_example(example):
    result = assistant.classify_intent(example["question"])
    assert result.intent == example["intent"]


def test_examples_cover_all_supported_intents():
    intents = {e["intent"] for e in assistant.EXAMPLE_QUESTIONS}
    assert intents == {
        assistant.INTENT_EXPLAIN_DEGRADATION,
        assistant.INTENT_SCENARIO_IMPACT,
        assistant.INTENT_OPTIMIZE_ENERGY,
        assistant.INTENT_GENERATOR_PRIORITY,
        assistant.INTENT_SHOW_EVIDENCE,
        assistant.INTENT_DRAFT_WORK_ORDER,
        assistant.INTENT_SHIFT_SUMMARY,
        assistant.INTENT_WATER_QUALITY_STATUS,
    }


def test_target_resolution_maps_common_references():
    assert assistant.resolve_target("why is HPP-001 degrading") == "AST-HPP-01"
    assert assistant.resolve_target("membrane cleaning") == "AST-MEMB-01"
    assert assistant.resolve_target("energy recovery device") == "AST-ERD-01"
    assert assistant.resolve_target("cartridge filter dp") == "AST-CF-01"


# --- Grounded degradation answer -------------------------------------------


def test_answer_degradation_includes_health_and_root_cause_and_evidence():
    resp = assistant.answer("Why is HPP-001 degrading?")
    assert resp.intent == assistant.INTENT_EXPLAIN_DEGRADATION
    assert resp.target == "AST-HPP-01"
    # Evidence block is populated (assets reviewed non-empty).
    assert resp.evidence.assets_reviewed == ["AST-HPP-01"]
    assert resp.evidence.documents_reviewed  # documents retrieved
    assert resp.evidence.data_timestamp
    # Health + root-cause context were aggregated and surfaced in the answer.
    assert "health" in resp.answer.lower()
    assert "root cause" in resp.answer.lower()
    # A grounded recommendation is present, pending, with control write disabled.
    assert resp.recommended_action is not None
    assert resp.recommended_action.approval_status.value == "pending"
    assert resp.recommended_action.ranked_causes
    assert resp.recommended_action.control_boundary.control_write_enabled is False


def test_answer_carries_control_boundary_confidence_and_evidence():
    for example in assistant.EXAMPLE_QUESTIONS:
        resp = assistant.answer(example["question"])
        assert resp.control_boundary.control_write_enabled is False
        assert resp.control_boundary.operator_approval_required is True
        assert 0.0 <= resp.confidence <= 1.0
        assert resp.evidence is not None
        assert resp.grounded is True
        assert resp.approval_required is True
        # Grounded answers must cite platform data and/or documents.
        assert resp.evidence.assets_reviewed or resp.evidence.documents_reviewed


# --- S3M-Core fallback ------------------------------------------------------


class _BrokenConnector(S3mConnector):
    """A connector that always fails, simulating an unreachable S3M-Core."""

    def __init__(self):
        super().__init__(base_url="http://s3m-core.invalid:9", timeout=0.01)


def test_answer_falls_back_to_local_when_s3m_core_unreachable():
    resp = assistant.answer("Why is HPP-001 degrading?", connector=_BrokenConnector())
    assert resp.source_engine_status == FALLBACK_LOCAL
    # Still grounded with populated evidence.
    assert resp.grounded is True
    assert resp.evidence.assets_reviewed == ["AST-HPP-01"]
    assert resp.evidence.documents_reviewed
    assert resp.recommended_action is not None


def test_answer_uses_quad_engine_when_connector_succeeds(monkeypatch):
    class _LiveConnector(S3mConnector):
        def submit_packet(self, packet):
            return ConnectorResult(
                source_engine_status="quad-engine",
                outputs={"operational_summary": "ok"},
                confidence=0.7,
            )

    resp = assistant.answer("What is the current water quality status?", connector=_LiveConnector())
    assert resp.source_engine_status == "quad-engine"
    assert resp.grounded is True


# --- Insufficient data (never fabricated) ----------------------------------


def test_answer_returns_insufficient_data_when_no_context():
    resp = assistant.answer("How many moons does Jupiter have?")
    assert resp.intent == assistant.INTENT_UNKNOWN
    assert "insufficient data" in resp.answer.lower()
    assert resp.evidence.assets_reviewed == []
    assert resp.evidence.documents_reviewed == []
    assert resp.recommended_action is None
    assert resp.confidence == 0.0
    # Even the refusal carries the control boundary + evidence block.
    assert resp.control_boundary.control_write_enabled is False


def test_answer_insufficient_for_unknown_asset_degradation():
    resp = assistant.answer("Why is XYZ-999 degrading?")
    assert resp.intent == assistant.INTENT_EXPLAIN_DEGRADATION
    assert "insufficient data" in resp.answer.lower()
    assert resp.recommended_action is None


# --- API surface ------------------------------------------------------------


def test_ask_endpoint_persists_recommendation_and_audits(client):
    resp = client.post("/api/v1/assistant/ask", json={"question": "Why is HPP-001 degrading?"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["control_boundary"]["control_write_enabled"] is False
    assert body["evidence"]["assets_reviewed"] == ["AST-HPP-01"]
    rec_id = body["recommended_action"]["recommendation_id"]

    # Routed through the existing recommendation + audit path.
    listed = client.get("/api/v1/recommendations").json()
    assert any(r["recommendation_id"] == rec_id for r in listed)
    events = client.get("/api/v1/audit").json()["events"]
    kinds = {e["kind"] for e in events}
    assert "assistant.ask" in kinds
    assert "assistant.recommendation.created" in kinds


def test_ask_endpoint_is_idempotent_for_recommendation(client):
    client.post("/api/v1/assistant/ask", json={"question": "Why is HPP-001 degrading?"})
    client.post("/api/v1/assistant/ask", json={"question": "Why is HPP-001 degrading?"})
    listed = client.get("/api/v1/recommendations").json()
    matches = [
        r for r in listed if r["recommendation_id"] == "rec-assistant-explain_degradation-ast-hpp-01"
    ]
    assert len(matches) == 1


def test_examples_endpoint_lists_canonical_questions(client):
    body = client.get("/api/v1/assistant/examples").json()
    assert len(body["examples"]) == len(assistant.EXAMPLE_QUESTIONS)
    assert body["control_boundary"]["control_write_enabled"] is False


def test_ask_insufficient_data_via_api(client):
    body = client.post(
        "/api/v1/assistant/ask", json={"question": "How many moons does Jupiter have?"}
    ).json()
    assert "insufficient data" in body["answer"].lower()
    assert body["recommended_action"] is None
    assert body["source_engine_status"] == FALLBACK_LOCAL


# --- Document store ---------------------------------------------------------


def test_documents_endpoint_lists_seeded_corpus(client):
    body = client.get("/api/v1/documents").json()
    ids = {d["document_id"] for d in body["documents"]}
    assert {"MAN-HPP-001", "PROC-ISO-HPP-001", "PROC-CIP-MEMB-001", "PROC-CF-REPL-001",
            "REC-MAINT-HIST-001"} <= ids
    types = {d["document_type"] for d in body["documents"]}
    assert {"manual", "procedure", "maintenance_record"} <= types


def test_document_get_and_404(client):
    ok = client.get("/api/v1/documents/PROC-CIP-MEMB-001")
    assert ok.status_code == 200
    assert "Clean-In-Place" in ok.json()["content"]
    assert client.get("/api/v1/documents/NOPE").status_code == 404


def test_retrieval_ranks_relevant_documents_first():
    refs = documents.retrieve("high-pressure pump bearing vibration isolation", k=3)
    assert refs
    ids = [r.document_id for r in refs]
    # The HP-pump manual and the pump isolation procedure are the most relevant.
    assert "MAN-HPP-001" in ids or "PROC-ISO-HPP-001" in ids
    assert all(r.score and r.score > 0 for r in refs)


def test_retrieval_returns_empty_for_no_keyword_overlap():
    assert documents.retrieve("the a of to", k=3) == []
