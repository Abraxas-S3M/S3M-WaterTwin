"""Shared domain schemas for the WaterTwin service.

These models define the data contract between the WaterTwin edge, the S3M-Core
quad-engine, and the operator-facing recommendation layer. They are intentionally
advisory-only: nothing in this module (or anything that consumes it) is permitted
to issue a control write to physical equipment. The ``control_write_enabled`` flag
is the machine-readable expression of that boundary and defaults to ``False``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PacketType(StrEnum):
    """Classification of a packet handed to the quad-engine."""

    ALERT = "alert"
    ROUTINE = "routine"


class ApprovalStatus(StrEnum):
    """Operator approval lifecycle for a recommendation card."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# Canonical set of analytical outputs the WaterTwin requests from the quad-engine.
DEFAULT_REQUESTED_OUTPUTS: tuple[str, ...] = (
    "operational_summary",
    "root_cause_analysis",
    "risk_forecast",
    "recommended_actions",
    "operator_explanation",
)


class RankedCause(BaseModel):
    """A candidate root cause with a probability and supporting evidence."""

    cause: str
    probability: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    """Provenance for an assessment: what was reviewed and under what assumptions."""

    telemetry_window: dict[str, Any] = Field(default_factory=dict)
    assets_reviewed: list[str] = Field(default_factory=list)
    docs_reviewed: list[str] = Field(default_factory=list)
    simulation_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    data_timestamp: datetime = Field(default_factory=_utcnow)


class WaterTwinPacket(BaseModel):
    """A packet emitted by the WaterTwin edge for analysis by the quad-engine."""

    packet_type: PacketType = PacketType.ROUTINE
    facility_id: str
    train_id: str
    asset_id: str
    domain: str = "water"
    telemetry: dict[str, Any] = Field(default_factory=dict)
    anomaly: dict[str, Any] = Field(default_factory=dict)
    requested_outputs: list[str] = Field(default_factory=lambda: list(DEFAULT_REQUESTED_OUTPUTS))
    ts: datetime = Field(default_factory=_utcnow)
    # Advisory boundary: the WaterTwin never authorises a control write.
    control_write_enabled: bool = False


class OperationalPacket(BaseModel):
    """S3M-Core quad-engine ingestion format adapted from a :class:`WaterTwinPacket`."""

    packet_type: str
    source: str = "watertwin"
    requested_outputs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=_utcnow)
    control_write_enabled: bool = False


class RecommendationCard(BaseModel):
    """Operator-facing recommendation produced by the quad-engine or local fallback."""

    recommendation_id: str
    asset_id: str
    ts: datetime = Field(default_factory=_utcnow)
    title: str = ""
    summary: str = ""
    root_cause: str = ""
    ranked_causes: list[RankedCause] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    operator_explanation: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    # "core" when produced by S3M-Core, "fallback_local" on graceful degradation.
    source_engine_status: str = "core"
    evidence: Evidence | None = None
    # Advisory boundary is preserved regardless of which engine produced the card.
    control_write_enabled: bool = False

    def as_card_payload(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dict suitable for durable storage."""
        return self.model_dump(mode="json")
