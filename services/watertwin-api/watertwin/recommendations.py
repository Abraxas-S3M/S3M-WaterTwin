"""Assemble recommendation packets and build recommendation cards."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .analytics import compute_anomaly, compute_health
from .boundary import current_boundary
from .connector import S3MConnector
from .models import RecommendationCard
from .plant import SyntheticPlant
from .store import Store


def assemble_packet(asset_id: str, plant: SyntheticPlant, store: Store) -> dict[str, Any]:
    """Gather everything S3M-Core needs to reason about one asset."""

    asset = plant.get_asset(asset_id)
    specs = plant.metric_specs(asset_id)
    latest = store.latest_for(asset_id)
    history = store.history_for(asset_id)

    health = compute_health(asset_id, latest, specs)
    anomaly = compute_anomaly(asset_id, history, specs)

    return {
        "asset": asset.model_dump() if asset else {"id": asset_id},
        "latest_telemetry": latest.model_dump(mode="json") if latest else None,
        "health": health.model_dump(mode="json"),
        "anomaly": anomaly.model_dump(mode="json"),
        "control_boundary": current_boundary().model_dump(),
    }


def generate_recommendation(
    asset_id: str,
    plant: SyntheticPlant,
    store: Store,
    connector: S3MConnector,
    actor: str = "system",
) -> RecommendationCard:
    """Full generation flow: packet -> connector -> save -> audit -> card."""

    packet = assemble_packet(asset_id, plant, store)
    payload = connector.generate_recommendation(packet)

    card = RecommendationCard(
        id=str(uuid4()),
        asset_id=asset_id,
        title=payload.get("title", f"Recommendation for {asset_id}"),
        summary=payload.get("summary", ""),
        rationale=payload.get("rationale", ""),
        severity=payload.get("severity", "low"),
        recommended_actions=payload.get("recommended_actions", []),
        approval_status="pending",
        source=payload.get("source", "local-fallback"),
        created_at=datetime.now(UTC),
        packet=packet,
        control_boundary=current_boundary(),
    )
    store.save_recommendation(card)
    store.add_audit(
        event_type="recommendation.generated",
        actor=actor,
        subject=card.id,
        details={
            "asset_id": asset_id,
            "severity": card.severity,
            "source": card.source,
        },
    )
    return card
