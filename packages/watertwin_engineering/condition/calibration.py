"""Confidence calibration for condition scores.

A model that says "80% confident" should be right about 80% of the time. This
module measures and corrects that. Given a set of raw model scores (severities in
``[0, 1]``, treated as predicted event probabilities) and their observed binary
outcomes it builds a **reliability histogram**: scores are bucketed into bins and
each bin's mean predicted confidence is compared with the empirical fraction of
positives actually observed in that bin.

From the histogram it reports:

* **ECE** -- expected calibration error, the sample-weighted mean gap between
  predicted confidence and empirical accuracy across bins (lower = better);
* **MCE** -- the worst single-bin gap; and
* **Brier score** -- the mean squared error of the raw probabilities.

It also yields a monotone-free *recalibration map* (histogram binning): each raw
score is mapped to the empirical positive-rate of its bin, so a downstream
consumer can report a calibrated confidence. Pure and deterministic; every result
is stamped ``provenance = "preliminary"``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .backtest import wilson_interval
from .model_spec import PRELIMINARY, clamp

__all__ = [
    "CalibrationBin",
    "CalibrationResult",
    "calibrate",
]


@dataclass(frozen=True)
class CalibrationBin:
    """One reliability-histogram bin with its predicted-vs-observed gap."""

    lower: float
    upper: float
    count: int
    mean_confidence: float
    empirical_accuracy: float
    accuracy_ci: tuple[float, float]

    @property
    def gap(self) -> float:
        """Absolute calibration gap for the bin (``|confidence - accuracy|``)."""
        return abs(self.mean_confidence - self.empirical_accuracy)


@dataclass(frozen=True)
class CalibrationResult:
    """Calibration summary + a recalibration map over the score range."""

    n_bins: int
    samples: int
    ece: float
    mce: float
    brier: float
    bins: list[CalibrationBin] = field(default_factory=list)
    provenance: str = PRELIMINARY

    def calibrated_confidence(self, score: float) -> float:
        """Map a raw score to the empirical positive-rate of its bin.

        Bins with no observed samples fall back to the identity (the raw score),
        so the map is always defined across ``[0, 1]``.
        """
        s = clamp(float(score), 0.0, 1.0)
        for b in self.bins:
            # Upper-inclusive only for the final bin so 1.0 maps correctly.
            in_bin = b.lower <= s < b.upper or (s == b.upper == 1.0)
            if in_bin:
                return b.empirical_accuracy if b.count > 0 else round(s, 4)
        return round(s, 4)


def calibrate(
    scores: Sequence[float],
    labels: Sequence[bool],
    *,
    n_bins: int = 10,
) -> CalibrationResult:
    """Build a reliability histogram + calibration metrics for scored outcomes.

    Args:
        scores: Raw model scores in ``[0, 1]`` (predicted event probabilities).
        labels: Matching ground-truth outcomes (truthy = event occurred).
        n_bins: Number of equal-width reliability bins over ``[0, 1]``.

    Returns:
        A :class:`CalibrationResult` with per-bin reliability, ECE/MCE, Brier
        score and a recalibration map (``provenance = "preliminary"``).

    Raises:
        ValueError: If the inputs are empty, mismatched, or ``n_bins < 1``.
    """
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1.")
    if len(scores) != len(labels):
        raise ValueError("scores and labels must be the same length.")
    n = len(scores)
    if n == 0:
        raise ValueError("scores/labels must be non-empty.")

    width = 1.0 / n_bins
    bin_scores: list[list[float]] = [[] for _ in range(n_bins)]
    bin_labels: list[list[int]] = [[] for _ in range(n_bins)]

    brier_acc = 0.0
    for raw, label in zip(scores, labels, strict=True):
        s = clamp(float(raw), 0.0, 1.0)
        y = 1 if label else 0
        brier_acc += (s - y) ** 2
        # Final bin is upper-inclusive so a score of exactly 1.0 is counted.
        idx = min(int(s / width), n_bins - 1)
        bin_scores[idx].append(s)
        bin_labels[idx].append(y)

    bins: list[CalibrationBin] = []
    ece = 0.0
    mce = 0.0
    for i in range(n_bins):
        count = len(bin_scores[i])
        lower = round(i * width, 4)
        upper = round((i + 1) * width, 4)
        if count:
            mean_conf = sum(bin_scores[i]) / count
            positives = sum(bin_labels[i])
            accuracy = positives / count
            gap = abs(mean_conf - accuracy)
            ece += (count / n) * gap
            mce = max(mce, gap)
            ci = wilson_interval(positives, count)
        else:
            mean_conf = 0.0
            accuracy = 0.0
            ci = (0.0, 0.0)
        bins.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=count,
                mean_confidence=round(mean_conf, 4),
                empirical_accuracy=round(accuracy, 4),
                accuracy_ci=ci,
            )
        )

    return CalibrationResult(
        n_bins=n_bins,
        samples=n,
        ece=round(ece, 4),
        mce=round(mce, 4),
        brier=round(brier_acc / n, 4),
        bins=bins,
    )
