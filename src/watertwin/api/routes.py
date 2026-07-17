"""Read-only API routes for S3M-WaterTwin.

Only ``GET`` (read) and ``POST`` (compute-and-return) methods are used, and no
route mutates external state or commands equipment. The analytics route is a
pure function of its request body: it computes and returns advisory metrics.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from watertwin import __version__
from watertwin.logging_config import get_logger
from watertwin.models.analytics import TrainAnalytics, build_train_analytics
from watertwin.models.telemetry import TrainTelemetry
from watertwin.safety import SafetyEnvelope, assert_advisory_only, default_safety_envelope

logger = get_logger("api")

router = APIRouter()


class ServiceInfo(BaseModel):
    """Basic service identity and posture."""

    name: str
    version: str
    description: str
    control_mode: Literal["advisory"]
    read_only: Literal[True]


class HealthStatus(BaseModel):
    """Liveness response."""

    status: Literal["ok"]
    version: str


@router.get("/", response_model=ServiceInfo, tags=["meta"], summary="Service information")
def service_info() -> ServiceInfo:
    """Return service identity and confirm the advisory, read-only posture."""

    return ServiceInfo(
        name="s3m-watertwin",
        version=__version__,
        description=(
            "Read-only, advisory digital twin for one seawater RO treatment "
            "train. Recommends only; a human decides."
        ),
        control_mode="advisory",
        read_only=True,
    )


@router.get("/health", response_model=HealthStatus, tags=["meta"], summary="Liveness check")
def health() -> HealthStatus:
    """Report service liveness."""

    return HealthStatus(status="ok", version=__version__)


@router.get(
    "/safety",
    response_model=SafetyEnvelope,
    tags=["safety"],
    summary="Advisory safety envelope",
)
def safety() -> SafetyEnvelope:
    """Return the advisory-only safety envelope in force.

    The envelope is asserted before it is returned, so a violated boundary would
    surface as an error rather than a silently unsafe response.
    """

    return assert_advisory_only(default_safety_envelope())


@router.post(
    "/analytics/train",
    response_model=TrainAnalytics,
    tags=["analytics"],
    summary="Compute preliminary RO-train analytics",
)
def analytics_train(telemetry: TrainTelemetry) -> TrainAnalytics:
    """Compute preliminary, advisory analytics from a synthetic telemetry packet.

    This route reads the request body and returns derived engineering metrics.
    It performs no control writes and mutates no external state.
    """

    analytics = build_train_analytics(telemetry)
    logger.info(
        "Computed preliminary train analytics.",
        extra={
            "train_id": analytics.train_id,
            "provenance": telemetry.provenance,
            "analytics_status": analytics.status,
            "recovery_fraction": analytics.recovery_fraction,
        },
    )
    return analytics
