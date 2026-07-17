"""Preliminary analytics schema for one RO train.

Analytics packets carry derived engineering metrics plus explicit truthfulness
metadata. The ``status`` field is a ``Literal["preliminary"]`` and every packet
includes a fixed disclaimer so downstream consumers (including S3M-Core) cannot
mistake advisory output for a validated production prediction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from watertwin.engineering.train import TrainEvaluation, evaluate_train
from watertwin.models.telemetry import TrainTelemetry
from watertwin.safety import SafetyEnvelope, default_safety_envelope

#: The only permitted analytics status. All analytics are preliminary.
AnalyticsStatus = Literal["preliminary"]

DISCLAIMER = (
    "Preliminary, advisory analytics derived from synthetic telemetry using "
    "deterministic engineering approximations. Not a validated production "
    "prediction, guaranteed saving, compliance certification, or autonomous "
    "control action. A human operator must review and approve any action."
)


class TrainAnalytics(BaseModel):
    """Derived, advisory metrics for one RO train.

    Concentrations are in mg/L, pressures in bar, flows in m^3/h, flux in LMH,
    and SEC in kWh/m^3.
    """

    model_config = ConfigDict(extra="forbid")

    status: AnalyticsStatus = Field(
        default="preliminary",
        description="Analytics maturity. Always 'preliminary'.",
    )
    disclaimer: str = Field(
        default=DISCLAIMER,
        description="Truthfulness disclaimer attached to every analytics packet.",
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC time the analytics were generated.",
    )
    train_id: str = Field(..., description="Identifier of the evaluated RO train.")
    safety: SafetyEnvelope = Field(
        default_factory=default_safety_envelope,
        description="Advisory-only safety envelope in force for this packet.",
    )

    recovery_fraction: float = Field(..., ge=0, le=1)
    salt_rejection_fraction: float = Field(..., ge=0, le=1)
    salt_passage_fraction: float = Field(..., ge=0, le=1)
    concentration_factor: float = Field(..., ge=1)
    feed_osmotic_pressure_bar: float = Field(..., ge=0)
    concentrate_osmotic_pressure_bar: float = Field(..., ge=0)
    average_feed_side_osmotic_pressure_bar: float = Field(..., ge=0)
    permeate_osmotic_pressure_bar: float = Field(..., ge=0)
    net_driving_pressure_bar: float
    water_flux_lmh: float = Field(..., ge=0)
    temperature_correction_factor: float = Field(..., gt=0)
    normalized_permeate_flow_m3_per_h: float = Field(..., ge=0)
    specific_energy_consumption_kwh_per_m3: float = Field(..., ge=0)

    @classmethod
    def from_evaluation(cls, train_id: str, evaluation: TrainEvaluation) -> TrainAnalytics:
        """Build an analytics packet from a deterministic train evaluation."""

        return cls(
            train_id=train_id,
            recovery_fraction=evaluation.recovery_fraction,
            salt_rejection_fraction=evaluation.salt_rejection_fraction,
            salt_passage_fraction=evaluation.salt_passage_fraction,
            concentration_factor=evaluation.concentration_factor,
            feed_osmotic_pressure_bar=evaluation.feed_osmotic_pressure_bar,
            concentrate_osmotic_pressure_bar=evaluation.concentrate_osmotic_pressure_bar,
            average_feed_side_osmotic_pressure_bar=(
                evaluation.average_feed_side_osmotic_pressure_bar
            ),
            permeate_osmotic_pressure_bar=evaluation.permeate_osmotic_pressure_bar,
            net_driving_pressure_bar=evaluation.net_driving_pressure_bar,
            water_flux_lmh=evaluation.water_flux_lmh,
            temperature_correction_factor=evaluation.temperature_correction_factor,
            normalized_permeate_flow_m3_per_h=(evaluation.normalized_permeate_flow_m3_per_h),
            specific_energy_consumption_kwh_per_m3=(
                evaluation.specific_energy_consumption_kwh_per_m3
            ),
        )


def build_train_analytics(telemetry: TrainTelemetry) -> TrainAnalytics:
    """Run the deterministic engine on synthetic telemetry and package results.

    This is the single seam between the physics engine and the analytics schema.
    """

    evaluation = evaluate_train(
        feed_pressure_bar=telemetry.feed_pressure_bar,
        permeate_pressure_bar=telemetry.permeate_pressure_bar,
        feed_flow_m3_per_h=telemetry.feed_flow_m3_per_h,
        permeate_flow_m3_per_h=telemetry.permeate_flow_m3_per_h,
        feed_tds_mg_per_l=telemetry.feed_tds_mg_per_l,
        permeate_tds_mg_per_l=telemetry.permeate_tds_mg_per_l,
        temperature_c=telemetry.temperature_c,
        membrane_permeability_lmh_per_bar=telemetry.membrane_permeability_lmh_per_bar,
        feed_channel_dp_bar=telemetry.feed_channel_dp_bar,
        pump_efficiency=telemetry.pump_efficiency,
        energy_recovery_efficiency=telemetry.energy_recovery_efficiency,
    )
    return TrainAnalytics.from_evaluation(telemetry.train_id, evaluation)
