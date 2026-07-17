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

from watertwin_engineering import calculations
from watertwin_engineering.calculations import (
    ROReference,
    ro_performance,
    specific_energy,
)
from watertwin_engineering.osmotic import (
    osmotic_pressure_bar,
    seawater_osmotic_pressure_bar,
)
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

__all__ = [
    "ROReference",
    "TrainEvaluation",
    "calculations",
    "concentration_factor",
    "evaluate_train",
    "net_driving_pressure_bar",
    "osmotic_pressure_bar",
    "recovery_fraction",
    "ro_performance",
    "salt_passage_fraction",
    "salt_rejection_fraction",
    "seawater_osmotic_pressure_bar",
    "specific_energy",
    "specific_energy_consumption_kwh_per_m3",
    "temperature_correction_factor",
    "water_flux_lmh",
]
