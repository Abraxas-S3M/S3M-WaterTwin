"""In-memory recommendation + audit store for the reference API.

Not a database — process-local state that resets on restart. It exists so the
dashboard's approve/reject actions round-trip to the API and appear in an audit
trail, satisfying the Phase 7 acceptance criteria. The real Phase 6 backend
persists these.
"""

from __future__ import annotations

import threading
import uuid
from typing import Optional

from .canonical_water_model import (
    ApprovalStatus,
    ControlBoundary,
    DataProvenance,
    Evidence,
    RankedCause,
    RecommendationCard,
    now_iso,
)
from .synthetic import (
    ASSET_INDEX,
    FACILITY_ID,
    TRAIN_ID,
    anomaly_for,
    health_for,
)

CONTROL_BOUNDARY = ControlBoundary()

_lock = threading.RLock()
_recommendations: dict[str, RecommendationCard] = {}
_audit: list[dict] = []


def _audit_add(entry: dict) -> None:
    entry = {"id": str(uuid.uuid4()), "timestamp": now_iso(), **entry}
    _audit.insert(0, entry)


_CAUSE_LIBRARY: dict[str, list[tuple[str, float, str]]] = {
    "hp_pump": [
        ("Impeller wear reducing hydraulic efficiency", 0.46,
         "Head/flow operating point drifted 6% below curve over 21 days"),
        ("Drive-end bearing degradation", 0.31,
         "Vibration RMS rising toward alarm; 1x/2x running-speed components"),
        ("Suction throttling / partial cavitation", 0.14,
         "Suction pressure margin narrowing at peak demand"),
    ],
    "membrane_array": [
        ("Organic/biological fouling of lead elements", 0.52,
         "Normalized salt passage up 18% and dP rising vs baseline"),
        ("Scaling from antiscalant underdosing", 0.27,
         "Recovery-normalized dP trend correlates with dosing dips"),
        ("Sensor drift on permeate conductivity", 0.11,
         "Conductivity variance inconsistent with feed TDS"),
    ],
    "default": [
        ("Efficiency drift from mechanical wear", 0.4,
         "Preliminary trend analysis on 14-day telemetry window"),
        ("Instrumentation drift", 0.2,
         "Cross-check against redundant sensors recommended"),
    ],
}

_ACTION_LIBRARY: dict[str, str] = {
    "hp_pump": "Schedule vibration diagnostic and inspect drive-end bearing at next "
               "maintenance window; verify operating point against pump curve.",
    "membrane_array": "Plan CIP (clean-in-place) for lead elements and audit antiscalant "
                      "dosing setpoints; sample permeate for conductivity verification.",
    "default": "Increase monitoring cadence and schedule inspection; confirm sensor calibration.",
}


def generate_recommendation(asset_id: str) -> RecommendationCard:
    """S3M stand-in: synthesize a ranked-cause recommendation for an asset."""
    asset = ASSET_INDEX.get(asset_id)
    atype = asset.asset_type.value if asset else "default"
    key = atype if atype in _CAUSE_LIBRARY else "default"
    causes_src = _CAUSE_LIBRARY.get(key, _CAUSE_LIBRARY["default"])
    action = _ACTION_LIBRARY.get(key, _ACTION_LIBRARY["default"])

    health = health_for(asset_id)
    anomaly = anomaly_for(asset_id)
    rec_id = f"REC-{uuid.uuid4().hex[:8].upper()}"
    packet_id = f"PKT-{uuid.uuid4().hex[:8].upper()}"
    now = now_iso()

    causes = [RankedCause(cause=c, probability=p, evidence=e) for c, p, e in causes_src]
    evidence = Evidence(
        telemetry_window="14d",
        assets_reviewed=[asset_id],
        documents_reviewed=["O&M manual", "commissioning baseline"],
        simulation_ids=[],
        assumptions=[
            "Synthetic telemetry used in place of live plant historian",
            "Preliminary model weights pending Phase 8-9 calibration",
        ],
        data_timestamp=now,
    )
    card = RecommendationCard(
        recommendation_id=rec_id,
        packet_id=packet_id,
        facility_id=asset.facility_id if asset else FACILITY_ID,
        train_id=asset.train_id if asset else TRAIN_ID,
        asset_id=asset_id,
        treatment_stage=asset.treatment_stage if asset else None,
        summary=(
            f"{asset.name if asset else asset_id}: health {health.score} "
            f"({health.band.value}), anomaly {anomaly.score}. Ranked causes identified."
        ),
        ranked_causes=causes,
        recommended_action=action,
        confidence=round(min(0.95, 0.5 + anomaly.score * 0.4), 2),
        evidence=evidence,
        control_boundary=CONTROL_BOUNDARY,
        approval_status=ApprovalStatus.pending,
        source_engine_status="preliminary",
        created_at=now,
    )
    with _lock:
        _recommendations[rec_id] = card
        _audit_add(
            {
                "action": "recommendation_created",
                "recommendation_id": rec_id,
                "asset_id": asset_id,
                "actor": "s3m-engine",
                "detail": card.summary,
            }
        )
    return card


def _seed_initial() -> None:
    """Seed a couple of standing recommendations so the overview isn't empty."""
    with _lock:
        if _recommendations:
            return
    for asset_id in ("AST-HPP-01", "AST-MEMB-01"):
        generate_recommendation(asset_id)


def list_recommendations(asset_id: Optional[str] = None) -> list[RecommendationCard]:
    with _lock:
        items = list(_recommendations.values())
    if asset_id:
        items = [r for r in items if r.asset_id == asset_id]
    return sorted(items, key=lambda r: r.created_at, reverse=True)


def get_recommendation(rec_id: str) -> Optional[RecommendationCard]:
    with _lock:
        return _recommendations.get(rec_id)


def decide_recommendation(
    rec_id: str, decision: ApprovalStatus, operator: str, note: Optional[str]
) -> Optional[RecommendationCard]:
    with _lock:
        card = _recommendations.get(rec_id)
        if card is None:
            return None
        card.approval_status = decision
        _audit_add(
            {
                "action": f"recommendation_{decision.value}",
                "recommendation_id": rec_id,
                "asset_id": card.asset_id,
                "actor": operator,
                "note": note or "",
                "detail": f"Operator {decision.value} '{card.recommended_action}'",
            }
        )
        return card


def list_audit(asset_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    with _lock:
        items = list(_audit)
    if asset_id:
        items = [e for e in items if e.get("asset_id") == asset_id]
    return items[:limit]


def audit_provenance() -> str:
    return DataProvenance.preliminary.value


_seed_initial()
