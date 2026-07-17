"""Benchmark scaffolds for the D1 models.

Each module here is a runnable **benchmark stub** for one D1 model: it runs the
model over its synthetic back-test dataset and prints the preliminary benchmark
(back-test metrics + Brier score + drift status). These are scaffolds -- the
synthetic dataset is a placeholder to be replaced with a customer-labelled
dataset during calibration, at which point the thresholds move from preliminary
to validated. Nothing here writes to any control system.

Run one with, e.g.::

    python -m app.models.benchmarks.pump_condition
"""

from __future__ import annotations
