"""Pydantic models shared across the WaterTwin service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .boundary import ControlBoundary


class Asset(BaseModel):
    """A physical plant asset (pump, membrane train, tank, valve, ...)."""

    id: str
    name: str
    asset_type: str
    location: str
    rated_capacity: float
    unit: str
    status: str = "running"
    installed_year: int


class TelemetryReading(BaseModel):
    """A single point-in-time set of metrics for one asset."""

    asset_id: str
    timestamp: datetime
    metrics: dict[str, float]


class HealthScore(BaseModel):
    asset_id: str
    score: float
    status: str
    factors: dict[str, float] = Field(default_factory=dict)
    computed_at: datetime
    control_boundary: ControlBoundary


class AnomalyResult(BaseModel):
    asset_id: str
    is_anomaly: bool
    score: float
    method: str
    metric: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime
    control_boundary: ControlBoundary


class RecommendationCard(BaseModel):
    id: str
    asset_id: str
    title: str
    summary: str
    rationale: str
    severity: str
    recommended_actions: list[str] = Field(default_factory=list)
    approval_status: str = "pending"
    source: str = "local-fallback"
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    packet: dict[str, Any] = Field(default_factory=dict)
    control_boundary: ControlBoundary


class AuditEvent(BaseModel):
    id: str
    timestamp: datetime
    event_type: str
    actor: str
    subject: str
    details: dict[str, Any] = Field(default_factory=dict)


class PlantSummary(BaseModel):
    scenario: str
    tick_count: int
    asset_count: int
    running: int
    faulted: int
    last_tick: datetime | None = None
    control_boundary: ControlBoundary


class DecisionRequest(BaseModel):
    status: str
    actor: str


class ScenarioRequest(BaseModel):
    scenario: str
