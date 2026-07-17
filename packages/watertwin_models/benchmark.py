"""D1 benchmark scaffold: aggregate back-test + calibration into one report.

:func:`run_benchmark` runs a model's ``predict_fn`` over a labelled synthetic
:class:`~watertwin_models.backtest.BackTestDataset`, then rolls the classification
metrics together with a Brier score and (optionally) a drift report into a single
:class:`BenchmarkResult`. Concrete per-model benchmark stubs call this to produce
a reproducible preliminary benchmark; the result is explicitly not a validated
performance guarantee.

Pure and deterministic; no I/O.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from canonical_water_model import DataProvenance
from watertwin_models.backtest import (
    BackTestDataset,
    BackTestMetrics,
    PredictFn,
    run_backtest,
)
from watertwin_models.calibration import ConfidenceCalibrator, brier_score
from watertwin_models.drift import DriftReport

#: Mandatory honesty stamp on every benchmark artifact.
BENCHMARK_DISCLAIMER = (
    "Preliminary benchmark on synthetic back-test data. Thresholds and metrics "
    "are screening figures pending customer calibration -- not validated "
    "performance or a guaranteed outcome. Advisory, read-only."
)


class BenchmarkResult(BaseModel):
    """Aggregated preliminary benchmark for one D1 model."""

    model_config = {"protected_namespaces": ()}

    model_id: str
    threshold: float
    backtest: BackTestMetrics
    brier_score: float
    drift: DriftReport | None = None
    thresholds_preliminary: bool = True
    pending_customer_calibration: bool = True
    provenance: DataProvenance = DataProvenance.preliminary
    disclaimer: str = BENCHMARK_DISCLAIMER
    notes: list[str] = Field(default_factory=list)


def run_benchmark(
    dataset: BackTestDataset,
    predict_fn: PredictFn,
    threshold: float = 0.5,
    calibrator: ConfidenceCalibrator | None = None,
    drift: DriftReport | None = None,
    notes: list[str] | None = None,
) -> BenchmarkResult:
    """Run the back-test + Brier score and assemble a preliminary benchmark.

    Args:
        dataset: The labelled synthetic dataset.
        predict_fn: Maps a sample's features to a probability in ``[0, 1]``.
        threshold: Decision threshold for the classification metrics.
        calibrator: Optional calibrator applied to the score before scoring the
            Brier component (an unfitted calibrator is an identity pass-through).
        drift: Optional drift report to attach.
        notes: Optional free-form notes.

    Returns:
        A preliminary :class:`BenchmarkResult`.
    """
    metrics: BackTestMetrics = run_backtest(dataset, predict_fn, threshold=threshold)

    cal = calibrator or ConfidenceCalibrator()
    probs = [cal.calibrate(float(predict_fn(s.features))) for s in dataset.samples]
    labels = [s.label for s in dataset.samples]
    brier = brier_score(probs, labels)

    return BenchmarkResult(
        model_id=dataset.model_id,
        threshold=threshold,
        backtest=metrics,
        brier_score=brier,
        drift=drift,
        notes=notes or [],
    )
