"""Synthetic telemetry schema for one RO train.

Every telemetry packet is explicitly synthetic. The ``provenance`` field is a
``Literal["synthetic"]`` so that no packet can claim to be real, validated,
production data. Membrane parameters accompany the readings so the deterministic
engineering math can be applied to a self-contained snapshot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: The only permitted telemetry provenance. All telemetry is synthetic.
Provenance = Literal["synthetic"]


class TrainTelemetry(BaseModel):
    """A single synthetic telemetry snapshot for one seawater RO train.

    Flows are in m^3/h, pressures in bar, concentrations in mg/L, temperature in
    degrees Celsius. Ranges are validated to keep inputs physically plausible.
    """

    model_config = ConfigDict(extra="forbid")

    provenance: Provenance = Field(
        default="synthetic",
        description="Data origin. Always 'synthetic'; never real production data.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC time the synthetic snapshot represents.",
    )
    train_id: str = Field(
        default="train-1",
        min_length=1,
        max_length=64,
        description="Identifier of the modelled RO train.",
    )

    feed_pressure_bar: float = Field(
        ..., gt=0, le=120, description="High-pressure pump discharge pressure, bar."
    )
    permeate_pressure_bar: float = Field(
        default=0.0, ge=0, le=20, description="Permeate-side back-pressure, bar."
    )
    feed_channel_dp_bar: float = Field(
        default=0.0, ge=0, le=10, description="Feed-to-concentrate friction drop, bar."
    )
    feed_flow_m3_per_h: float = Field(
        ..., gt=0, le=100000, description="Feed flow to the membranes, m^3/h."
    )
    permeate_flow_m3_per_h: float = Field(
        ..., gt=0, le=100000, description="Permeate production, m^3/h."
    )
    feed_tds_mg_per_l: float = Field(
        ..., gt=0, le=100000, description="Feed total dissolved solids, mg/L."
    )
    permeate_tds_mg_per_l: float = Field(
        ..., ge=0, le=100000, description="Permeate total dissolved solids, mg/L."
    )
    temperature_c: float = Field(
        ..., gt=-2, le=60, description="Feed temperature, degrees Celsius."
    )
    membrane_permeability_lmh_per_bar: float = Field(
        default=1.0,
        gt=0,
        le=20,
        description="Membrane water permeability A, in L/(m^2*h*bar).",
    )
    pump_efficiency: float = Field(
        default=0.8, gt=0, le=1, description="High-pressure pump efficiency, fraction."
    )
    energy_recovery_efficiency: float = Field(
        default=0.0, ge=0, le=1, description="Energy-recovery-device efficiency, fraction."
    )
