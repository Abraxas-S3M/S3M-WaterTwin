"""Core analysis-phase tests: acceptance defaults, degradation, idempotency,
provenance clamping, and audit capture."""

from __future__ import annotations

import pytest
from canonical_water_model import DataProvenance

from app.analysis import AnalysisCache, analyze_upload
from app.audit import KIND_ANALYSIS_RESPONSE, AuditChain
from app.models import (
    AI_PROVENANCE_CEILING,
    ProposedChange,
    SourceCitation,
    clamp_ai_provenance,
    provenance_rank,
)

from .fake_s3m import (
    MODEL_VERSION,
    FakeAnalysisClient,
    UnavailableClient,
    pump_curve_outputs,
    pump_curve_parse_result,
)


def _run(client, parse_result=None, cache=None, audit=None):
    parse_result = parse_result or pump_curve_parse_result()
    return analyze_upload(
        parse_result,
        approved_documents=[{"document_id": "DS-P003", "provenance": "measured"}],
        client=client,
        cache=cache or AnalysisCache(),
        audit=audit or AuditChain(),
    )


def test_ai_suggested_changes_arrive_unaccepted():
    client = FakeAnalysisClient(pump_curve_outputs())
    result = _run(client)

    assert result.available is True
    assert result.proposed_changes, "expected at least one drafted change"
    for change in result.proposed_changes:
        assert change.ai_suggested is True
        assert change.accepted is False
        assert change.accepted_by is None
        assert change.accepted_at is None
        assert change.ai_confidence is not None
        assert change.ai_rationale
        assert change.citation is not None


def test_acceptance_requires_explicit_named_operator():
    # A change only becomes accepted through the explicit human per-field opt-in.
    change = ProposedChange.from_draft(
        change_id="c1",
        field_path="pump.P-003.rated_efficiency_pct",
        proposed_value=78.0,
        ai_confidence=0.5,
        ai_rationale="drafted",
        citation=SourceCitation(document_id="ING-001", locator="rows 2-4"),
        source_provenance=DataProvenance.measured,
    )
    assert change.accepted is False

    with pytest.raises(ValueError):
        change.accept("")
    assert change.accepted is False

    change.accept("operator-jane")
    assert change.accepted is True
    assert change.accepted_by == "operator-jane"
    assert change.accepted_at is not None


def test_no_analysis_output_can_pre_accept_a_change():
    # Even if the upstream tries to mark a draft accepted, it arrives unaccepted.
    outputs = pump_curve_outputs()
    outputs["drafted_values"][0]["accepted"] = True
    outputs["drafted_values"][0]["ai_suggested"] = False
    client = FakeAnalysisClient(outputs)
    result = _run(client)

    assert result.proposed_changes
    assert all(c.accepted is False for c in result.proposed_changes)
    assert all(c.ai_suggested is True for c in result.proposed_changes)


def test_graceful_degradation_when_s3m_unavailable():
    client = UnavailableClient()
    result = _run(client)

    # The proposal still renders: a degraded, error-free result with no panel.
    assert result.available is False
    assert result.notice
    assert result.summary is None
    assert result.anomalies == []
    assert result.drafted_values == []
    assert result.proposed_changes == []
    assert result.source_engine_status == "fallback_local"


def test_idempotency_one_upstream_call_same_cached_result():
    client = FakeAnalysisClient(pump_curve_outputs())
    cache = AnalysisCache()
    audit = AuditChain()
    parse_result = pump_curve_parse_result()

    first = analyze_upload(parse_result, client=client, cache=cache, audit=audit)
    second = analyze_upload(parse_result, client=client, cache=cache, audit=audit)

    assert client.calls == 1, "repeat request must not re-query S3M-Core"
    assert first.parse_result_hash == second.parse_result_hash
    assert second is first  # served from cache


def test_changed_input_busts_the_cache():
    client = FakeAnalysisClient(pump_curve_outputs())
    cache = AnalysisCache()
    audit = AuditChain()

    analyze_upload(pump_curve_parse_result(), client=client, cache=cache, audit=audit)
    # A different file body changes the parse_result_hash -> a new upstream call.
    analyze_upload(
        pump_curve_parse_result(content="flow_m3h,head_m\n0,130\n"),
        client=client,
        cache=cache,
        audit=audit,
    )
    assert client.calls == 2


def test_degraded_result_is_not_cached_and_allows_retry():
    cache = AnalysisCache()
    audit = AuditChain()
    parse_result = pump_curve_parse_result()

    down = UnavailableClient()
    degraded = analyze_upload(parse_result, client=down, cache=cache, audit=audit)
    assert degraded.available is False

    # S3M-Core recovers: the retry succeeds (the degraded result was not cached).
    up = FakeAnalysisClient(pump_curve_outputs())
    recovered = analyze_upload(parse_result, client=up, cache=cache, audit=audit)
    assert recovered.available is True
    assert up.calls == 1


@pytest.mark.parametrize(
    "source",
    [
        DataProvenance.synthetic,
        DataProvenance.simulated,
        DataProvenance.preliminary,
        DataProvenance.measured,
    ],
)
def test_ai_change_never_outranks_source_provenance(source: DataProvenance):
    # The upstream claims the strongest possible label; it must be ignored and the
    # resulting provenance must not outrank the source file's provenance.
    outputs = pump_curve_outputs()
    outputs["drafted_values"][0]["provenance"] = "measured"
    client = FakeAnalysisClient(outputs)
    result = _run(client, parse_result=pump_curve_parse_result(source_provenance=source))

    assert result.proposed_changes
    for change in result.proposed_changes:
        assert provenance_rank(change.provenance) <= provenance_rank(source)
        assert provenance_rank(change.provenance) <= provenance_rank(AI_PROVENANCE_CEILING)


def test_clamp_helper_matches_invariant():
    assert clamp_ai_provenance(DataProvenance.measured) == DataProvenance.preliminary
    assert clamp_ai_provenance(DataProvenance.synthetic) == DataProvenance.synthetic
    assert clamp_ai_provenance(DataProvenance.preliminary) == DataProvenance.preliminary


def test_audit_captures_model_version_and_verifies():
    client = FakeAnalysisClient(pump_curve_outputs())
    audit = AuditChain()
    result = _run(client, audit=audit)

    responses = [e for e in audit.events() if e["kind"] == KIND_ANALYSIS_RESPONSE]
    assert responses, "a response must be audited"
    assert responses[-1]["payload"]["model_version"] == MODEL_VERSION
    assert result.model_version == MODEL_VERSION
    # The chain is tamper-evident and intact.
    assert audit.verify()["ok"] is True


def test_acceptance_criteria_cited_unaccepted_anomaly():
    # An uploaded pump curve that contradicts its nameplate produces a visible,
    # cited, unaccepted anomaly flag that a human must act on.
    client = FakeAnalysisClient(pump_curve_outputs())
    result = _run(client)

    assert result.anomalies, "expected the curve-vs-nameplate anomaly"
    anomaly = result.anomalies[0]
    assert "nameplate" in anomaly.message.lower()
    assert anomaly.citation.document_id == "ING-001"
    assert anomaly.citation.locator
    assert 0.0 <= anomaly.confidence <= 1.0
    # An anomaly flag changes no data and creates no accepted change.
    assert all(c.accepted is False for c in result.proposed_changes)
