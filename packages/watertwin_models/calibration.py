"""D1 confidence calibration: reliability binning + Brier score.

D1 models emit a physics-derived confidence in ``[0, 1]``. Until customer-
labelled outcomes exist, that confidence is **not** calibrated -- so this module
provides the transparent machinery to (a) measure calibration quality
(:func:`brier_score`, :func:`reliability_curve`) and (b) apply a fitted
reliability-binning calibrator (:class:`ConfidenceCalibrator`) once labels are
available. An unfitted calibrator is an identity pass-through, and every result
is flagged preliminary/uncalibrated so a raw confidence is never mistaken for a
validated probability.

Pure and deterministic; no I/O.
"""

from __future__ import annotations

from bisect import bisect_right

from pydantic import BaseModel


class ReliabilityBin(BaseModel):
    """One reliability-curve bin: mean predicted vs empirical frequency."""

    lower: float
    upper: float
    count: int
    mean_predicted: float
    empirical_frequency: float


def _validate_pairs(probs: list[float], labels: list[bool]) -> None:
    if len(probs) != len(labels):
        raise ValueError("probs and labels must have the same length.")
    if not probs:
        raise ValueError("probs/labels must be non-empty.")
    if any(not 0.0 <= p <= 1.0 for p in probs):
        raise ValueError("every probability must be in [0, 1].")


def brier_score(probs: list[float], labels: list[bool]) -> float:
    """Mean squared error between predicted probabilities and binary outcomes.

    Lower is better (0 = perfect). This is the standard proper scoring rule for
    probabilistic forecasts.
    """
    _validate_pairs(probs, labels)
    return round(
        sum((p - (1.0 if y else 0.0)) ** 2 for p, y in zip(probs, labels, strict=True))
        / len(probs),
        6,
    )


def reliability_curve(
    probs: list[float],
    labels: list[bool],
    n_bins: int = 10,
) -> list[ReliabilityBin]:
    """Bin predictions and compare mean predicted probability vs empirical rate.

    Returns one :class:`ReliabilityBin` per non-empty equal-width bin over
    ``[0, 1]``; a well-calibrated model has ``mean_predicted ~= empirical_
    frequency`` in every bin.
    """
    _validate_pairs(probs, labels)
    if n_bins <= 0:
        raise ValueError("n_bins must be positive.")

    width = 1.0 / n_bins
    bins: list[list] = [[0, 0.0, 0] for _ in range(n_bins)]  # [count, sum_pred, sum_pos]
    for p, y in zip(probs, labels, strict=True):
        idx = min(n_bins - 1, int(p / width))
        bins[idx][0] += 1
        bins[idx][1] += p
        bins[idx][2] += 1 if y else 0

    curve: list[ReliabilityBin] = []
    for i, (count, sum_pred, sum_pos) in enumerate(bins):
        if count == 0:
            continue
        curve.append(
            ReliabilityBin(
                lower=round(i * width, 4),
                upper=round((i + 1) * width, 4),
                count=count,
                mean_predicted=round(sum_pred / count, 4),
                empirical_frequency=round(sum_pos / count, 4),
            )
        )
    return curve


class ConfidenceCalibrator:
    """A reliability-binning confidence calibrator.

    Unfitted, :meth:`calibrate` is an identity pass-through (the raw confidence,
    flagged uncalibrated). Once :meth:`fit` is called with predicted
    probabilities and observed binary outcomes, ``calibrate`` maps a raw score to
    the empirical event frequency of its bin -- a transparent, monotone-by-bin
    recalibration. This is a screening calibrator, not a validated production
    model.
    """

    def __init__(self, n_bins: int = 10) -> None:
        if n_bins <= 0:
            raise ValueError("n_bins must be positive.")
        self.n_bins = n_bins
        self.calibrated = False
        self._edges: list[float] = []
        self._bin_freq: list[float] = []

    def fit(self, probs: list[float], labels: list[bool]) -> ConfidenceCalibrator:
        """Fit the calibrator from predicted probabilities + observed outcomes."""
        _validate_pairs(probs, labels)
        width = 1.0 / self.n_bins
        counts = [0] * self.n_bins
        positives = [0] * self.n_bins
        for p, y in zip(probs, labels, strict=True):
            idx = min(self.n_bins - 1, int(p / width))
            counts[idx] += 1
            positives[idx] += 1 if y else 0
        # Empirical frequency per bin; empty bins fall back to the bin centre so
        # calibration is defined across the whole [0, 1] range.
        self._edges = [i * width for i in range(1, self.n_bins)]
        self._bin_freq = [
            (positives[i] / counts[i]) if counts[i] else round((i + 0.5) * width, 6)
            for i in range(self.n_bins)
        ]
        self.calibrated = True
        return self

    def calibrate(self, score: float) -> float:
        """Map a raw confidence to a calibrated probability (identity if unfit)."""
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be in [0, 1].")
        if not self.calibrated:
            return score
        idx = bisect_right(self._edges, score)
        return round(self._bin_freq[idx], 6)
