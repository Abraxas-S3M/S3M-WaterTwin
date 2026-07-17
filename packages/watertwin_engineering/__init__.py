"""Deterministic engineering math for a seawater RO train.

This package is the single canonical "physics engine" for S3M-WaterTwin. Every
function here is a pure, deterministic engineering calculation with explicit
units and input validation. It never performs I/O: given the same inputs it
always returns the same outputs.

Two complementary reference models live here:

* the element/train solution-diffusion calculations (:mod:`.osmotic`,
  :mod:`.ro`, :mod:`.train`); and
* the lumped average-element analytical reference (:mod:`.calculations`), used
  for quick estimates and as an independent cross-check of the discretized
  ``treatment-sim`` engine.

Both share the single :func:`osmotic_pressure_bar` implementation; there is no
duplicate physics anywhere else in the repository.
"""

from __future__ import annotations

from watertwin_engineering import calculations, equipment, root_cause
from watertwin_engineering.calculations import (
    ROReference,
    ro_performance,
    specific_energy,
)
from watertwin_engineering.energy import (
    OperatingPoint,
    ROEnergyOptimization,
    avoidable_energy_loss,
    energy_cost,
    evaluate_operating_point,
    ro_operating_point_optimization,
)
from watertwin_engineering.equipment import (
    ComponentHealthResult,
    FailureProbabilityResult,
    HealthContribution,
    MaintenancePriorityResult,
    OperatingEnvelopeResult,
    RemainingUsefulLifeResult,
    component_health,
    failure_probability,
    health_band,
    maintenance_priority,
    operating_envelope_score,
    remaining_useful_life_days,
)
from watertwin_engineering.osmotic import (
    osmotic_pressure_bar,
    seawater_osmotic_pressure_bar,
)
from watertwin_engineering.resilience import (
    fuel_endurance_hours,
    generator_start_probability,
    load_shed_priority,
    resilience_criticality_score,
    service_continuity_hours,
)
from watertwin_engineering.root_cause import RootCause, root_cause_rank
from watertwin_engineering.ro import (
    concentration_factor,
    net_driving_pressure_bar,
    recovery_fraction,
    salt_passage_fraction,
    salt_rejection_fraction,
    specific_energy_consumption_kwh_per_m3,
    temperature_correction_factor,
    water_flux_lmh,
)
from watertwin_engineering.train import TrainEvaluation, evaluate_train
from watertwin_engineering.water_quality import (
    boron_rejection,
    colloidal_fouling_index,
    langelier_saturation_index,
    normalized_differential_pressure,
    normalized_salt_passage,
    silica_saturation_pct,
    sulfate_scaling_ratio,
)

__all__ = [
    "ComponentHealthResult",
    "FailureProbabilityResult",
    "HealthContribution",
    "MaintenancePriorityResult",
    "OperatingEnvelopeResult",
    "OperatingPoint",
    "ROEnergyOptimization",
    "ROReference",
    "RemainingUsefulLifeResult",
    "RootCause",
    "TrainEvaluation",
    "avoidable_energy_loss",
    "boron_rejection",
    "calculations",
    "colloidal_fouling_index",
    "component_health",
    "concentration_factor",
    "energy_cost",
    "equipment",
    "evaluate_operating_point",
    "evaluate_train",
    "failure_probability",
    "fuel_endurance_hours",
    "generator_start_probability",
    "health_band",
    "langelier_saturation_index",
    "load_shed_priority",
    "maintenance_priority",
    "net_driving_pressure_bar",
    "normalized_differential_pressure",
    "normalized_salt_passage",
    "operating_envelope_score",
    "osmotic_pressure_bar",
    "recovery_fraction",
    "remaining_useful_life_days",
    "resilience_criticality_score",
    "ro_operating_point_optimization",
    "ro_performance",
    "root_cause",
    "root_cause_rank",
    "salt_passage_fraction",
    "salt_rejection_fraction",
    "seawater_osmotic_pressure_bar",
    "service_continuity_hours",
    "silica_saturation_pct",
    "specific_energy",
    "specific_energy_consumption_kwh_per_m3",
    "sulfate_scaling_ratio",
    "temperature_correction_factor",
    "water_flux_lmh",
]
