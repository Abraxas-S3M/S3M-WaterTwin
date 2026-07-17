"""Benchmark stub for Model 2 -- membrane fouling & salt passage.

Scaffold only: runs the model over its synthetic back-test dataset and reports a
preliminary benchmark. Replace the synthetic dataset with a customer-labelled
dataset during calibration. Advisory / read-only.
"""

from __future__ import annotations

from watertwin_models import BenchmarkResult

from ..membrane_fouling import ADAPTER


def build_benchmark() -> BenchmarkResult:
    """Return the preliminary benchmark for the membrane fouling model."""
    return ADAPTER.benchmark()


def main() -> None:
    print(build_benchmark().model_dump_json(indent=2))


if __name__ == "__main__":  # pragma: no cover - manual scaffold entry point
    main()
