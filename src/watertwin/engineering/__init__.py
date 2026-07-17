"""Deterministic engineering math for a seawater RO train.

This subpackage is the "physics engine". Every function here is a pure,
deterministic engineering calculation with explicit units and input validation.
It never calls out to S3M-Core and never performs I/O: given the same inputs it
always returns the same outputs.
"""

from __future__ import annotations

from watertwin.engineering.osmotic import (
    osmotic_pressure_bar,
    seawater_osmotic_pressure_bar,
)
from watertwin.engineering.ro import (
    concentration_factor,
    net_driving_pressure_bar,
    recovery_fraction,
    salt_passage_fraction,
    salt_rejection_fraction,
    specific_energy_consumption_kwh_per_m3,
    temperature_correction_factor,
    water_flux_lmh,
)
from watertwin.engineering.train import TrainEvaluation, evaluate_train

__all__ = [
    "TrainEvaluation",
    "concentration_factor",
    "evaluate_train",
    "net_driving_pressure_bar",
    "osmotic_pressure_bar",
    "recovery_fraction",
    "salt_passage_fraction",
    "salt_rejection_fraction",
    "seawater_osmotic_pressure_bar",
    "specific_energy_consumption_kwh_per_m3",
    "temperature_correction_factor",
    "water_flux_lmh",
]
