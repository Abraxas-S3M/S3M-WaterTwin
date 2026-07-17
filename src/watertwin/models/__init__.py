"""Pydantic v2 data models for S3M-WaterTwin.

These schemas define the structured packets exchanged at the service boundary.
Two truthfulness invariants are baked into the types themselves:

* All telemetry is synthetic: ``provenance == "synthetic"``.
* All analytics are preliminary: ``status == "preliminary"``.
"""

from __future__ import annotations

from watertwin.models.analytics import (
    AnalyticsStatus,
    TrainAnalytics,
    build_train_analytics,
)
from watertwin.models.telemetry import Provenance, TrainTelemetry

__all__ = [
    "AnalyticsStatus",
    "Provenance",
    "TrainAnalytics",
    "TrainTelemetry",
    "build_train_analytics",
]
