"""Tests for the durable store, S3M-Core connector fallback, and HPP recommendations."""

from __future__ import annotations

from watertwin.recommendations import assess_hpp
from watertwin.s3m_connector import S3MConnector
from watertwin.schemas import ApprovalStatus, RecommendationCard
from watertwin.store import Store


def _degraded_hpp_telemetry() -> dict:
    """A high-pressure pump sample exhibiting multiple degradation signatures."""
    return {
        "suction_pressure_bar": 0.4,
        "discharge_pressure_bar": 58.0,
        "flow_m3h": 42.0,
        "motor_power_kw": 160.0,
        "feed_conductivity_us_cm": 52000.0,
        "permeate_conductivity_us_cm": 4200.0,
        "feed_flow_m3h": 100.0,
        "permeate_flow_m3h": 30.0,
        "vibration_mm_s": 9.2,
        "bearing_temp_c": 94.0,
        "npsh_required_m": 6.0,
        "ts": "2026-07-17T06:00:00+00:00",
    }


# --- Store --------------------------------------------------------------------


def test_store_without_db_is_in_memory():
    store = Store(database_url=None)
    assert store.db_connected is False


def test_store_audit_in_memory():
    store = Store(database_url=None)
    event = store.audit("test_event", {"foo": "bar"}, actor="tester")

    assert event["kind"] == "test_event"
    assert event["actor"] == "tester"

    recent = store.recent_audit(10)
    assert len(recent) == 1
    assert recent[0]["kind"] == "test_event"
    assert recent[0]["payload"] == {"foo": "bar"}


def test_store_save_and_get_recommendation_in_memory():
    store = Store(database_url=None)
    card = RecommendationCard(
        recommendation_id="rec-1",
        asset_id="hpp-001",
        title="test",
        recommended_actions=["do the advisory thing"],
    )
    store.save_recommendation(card)

    fetched = store.get_recommendation("rec-1")
    assert fetched is not None
    assert fetched.recommendation_id == "rec-1"
    assert fetched.asset_id == "hpp-001"
    assert fetched.control_write_enabled is False

    listed = store.list_recommendations()
    assert len(listed) == 1
    assert listed[0].recommendation_id == "rec-1"


def test_store_get_unknown_recommendation_returns_none():
    store = Store(database_url=None)
    assert store.get_recommendation("does-not-exist") is None


def test_store_set_approval_updates_status_and_writes_audit():
    store = Store(database_url=None)
    card = RecommendationCard(recommendation_id="rec-2", asset_id="hpp-002")
    store.save_recommendation(card)

    updated = store.set_approval("rec-2", "approved", actor="operator-jane")
    assert updated is not None
    assert updated.approval_status == ApprovalStatus.APPROVED

    stored = store.get_recommendation("rec-2")
    assert stored.approval_status == ApprovalStatus.APPROVED

    audit = store.recent_audit(10)
    assert any(
        e["kind"] == "recommendation_approval"
        and e["payload"]["recommendation_id"] == "rec-2"
        and e["payload"]["status"] == "approved"
        and e["actor"] == "operator-jane"
        for e in audit
    )


def test_store_set_approval_unknown_returns_none():
    store = Store(database_url=None)
    assert store.set_approval("nope", "approved", actor="op") is None


# --- S3M connector fallback ---------------------------------------------------


def test_submit_against_unreachable_core_returns_fallback_card():
    # Port chosen to be almost certainly closed; connection fails fast.
    connector = S3MConnector(core_url="http://127.0.0.1:59371", timeout=0.5)
    pkt = connector.build_packet(
        asset={"asset_id": "hpp-003"},
        telemetry=_degraded_hpp_telemetry(),
        anomaly={"type": "high_vibration"},
    )

    card = connector.submit(pkt)

    assert isinstance(card, RecommendationCard)
    assert card.source_engine_status == "fallback_local"
    assert card.control_write_enabled is False
    assert card.approval_status == ApprovalStatus.PENDING
    assert card.asset_id == "hpp-003"
    assert card.ranked_causes  # local analysis produced ranked causes


def test_build_packet_marks_anomaly_as_alert():
    connector = S3MConnector()
    pkt = connector.build_packet(
        asset={"asset_id": "hpp-004"},
        telemetry={"flow_m3h": 10.0},
        anomaly={"type": "cavitation"},
    )
    assert pkt.packet_type.value == "alert"
    assert pkt.control_write_enabled is False
    assert set(pkt.requested_outputs) >= {
        "operational_summary",
        "root_cause_analysis",
        "risk_forecast",
        "recommended_actions",
        "operator_explanation",
    }


def test_to_core_packet_preserves_domain_and_water_fields():
    connector = S3MConnector()
    pkt = connector.build_packet(
        asset={"asset_id": "hpp-005"},
        telemetry={"flow_m3h": 12.0},
    )
    core = connector._to_core_packet(pkt)
    assert core.payload["domain"] == "water"
    assert core.payload["asset_id"] == "hpp-005"
    assert core.payload["telemetry"] == {"flow_m3h": 12.0}
    assert core.control_write_enabled is False


def test_core_status_unreachable_is_best_effort():
    connector = S3MConnector(core_url="http://127.0.0.1:59371", timeout=0.5)
    status = connector.core_status()
    assert status["reachable"] is False


# --- recommendations ----------------------------------------------------------


def test_assess_hpp_degraded_returns_non_empty_ranked_causes():
    result = assess_hpp({"asset_id": "hpp-006"}, _degraded_hpp_telemetry())

    assert result.ranked_causes
    assert result.top_cause
    assert result.recommended_action
    assert 0.0 <= result.confidence <= 1.0

    # Probabilities are normalised (allowing for 4-decimal rounding).
    total = sum(rc.probability for rc in result.ranked_causes)
    assert abs(total - 1.0) < 1e-2

    # Each ranked cause carries supporting evidence.
    assert all(rc.evidence for rc in result.ranked_causes)


def test_assess_hpp_computes_metrics():
    result = assess_hpp({"asset_id": "hpp-007"}, _degraded_hpp_telemetry())
    assert result.metrics.head_m > 0
    assert result.metrics.hydraulic_power_kw > 0
    assert result.metrics.salt_passage > 0
    assert result.evidence is not None
    assert "hpp-007" in result.evidence.assets_reviewed


def test_assess_hpp_nominal_still_returns_ranked_causes():
    nominal = {
        "suction_pressure_bar": 3.0,
        "discharge_pressure_bar": 55.0,
        "flow_m3h": 100.0,
        "motor_power_kw": 190.0,
        "feed_conductivity_us_cm": 50000.0,
        "permeate_conductivity_us_cm": 500.0,
        "feed_flow_m3h": 100.0,
        "permeate_flow_m3h": 45.0,
        "vibration_mm_s": 1.8,
        "bearing_temp_c": 55.0,
        "npsh_required_m": 6.0,
    }
    result = assess_hpp({"asset_id": "hpp-008", "rated_efficiency": 0.5}, nominal)
    assert result.ranked_causes
