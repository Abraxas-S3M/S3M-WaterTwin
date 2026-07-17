"""Distribution-drift monitor for condition models.

A model validated on one operating regime silently degrades when the live data
drifts away from that regime (a new feed source, a sensor recalibration, a
seasonal shift). This monitor compares a **live window** of feature (and,
optionally, model-score) values against a frozen **baseline window** and raises a
drift flag before the model's alarms can be trusted less.

For each monitored feature it computes:

* the **Population Stability Index (PSI)** between the baseline and live
  distributions, binned on the baseline's deciles -- the standard measure of
  distribution shift (``< 0.1`` stable, ``0.1-0.2`` moderate, ``> 0.2``
  significant); and
* a **mean shift** expressed as a z-score against the baseline spread, so a
  shift carries its own statistical-significance context.

A feature is flagged when its PSI crosses ``psi_threshold``; the overall
``drift_flag`` fires when any monitored feature (or the score distribution) is
flagged. Pure and deterministic; results are stamped ``provenance =
"preliminary"``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .model_spec import PRELIMINARY, ConditionModel

#: Standard PSI threshold above which a distribution shift is "significant".
DEFAULT_PSI_THRESHOLD = 0.2

#: Pseudo-feature name under which the model-score distribution is monitored.
SCORE_FEATURE = "__score__"

#: Small floor so empty bins never produce a division-by-zero or log(0).
_EPS = 1e-6

__all__ = [
    "DEFAULT_PSI_THRESHOLD",
    "SCORE_FEATURE",
    "DriftResult",
    "FeatureDrift",
    "monitor_drift",
    "population_stability_index",
]


@dataclass(frozen=True)
class FeatureDrift:
    """Per-feature drift statistics between the baseline and live windows."""

    feature: str
    psi: float
    baseline_mean: float
    baseline_std: float
    live_mean: float
    mean_shift: float
    z_shift: float
    drift: bool


@dataclass(frozen=True)
class DriftResult:
    """Overall drift verdict across every monitored feature/score."""

    drift_flag: bool
    max_psi: float
    psi_threshold: float
    baseline_window: int
    live_window: int
    features: list[FeatureDrift] = field(default_factory=list)
    drifted_features: list[str] = field(default_factory=list)
    provenance: str = PRELIMINARY


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: Sequence[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _bin_edges(baseline: Sequence[float], n_bins: int) -> list[float]:
    """Quantile bin edges from the baseline (deciles by default), deduplicated."""
    ordered = sorted(baseline)
    edges = [-math.inf]
    for i in range(1, n_bins):
        q = i / n_bins
        pos = q * (len(ordered) - 1)
        lo = math.floor(pos)
        hi = math.ceil(pos)
        frac = pos - lo
        edge = ordered[lo] * (1 - frac) + ordered[hi] * frac
        if edge > edges[-1]:
            edges.append(edge)
    edges.append(math.inf)
    return edges


def _fractions(values: Sequence[float], edges: Sequence[float]) -> list[float]:
    counts = [0] * (len(edges) - 1)
    for v in values:
        for b in range(len(edges) - 1):
            if edges[b] < v <= edges[b + 1] or (b == 0 and v <= edges[b + 1]):
                counts[b] += 1
                break
    total = len(values) or 1
    return [c / total for c in counts]


def population_stability_index(
    baseline: Sequence[float],
    live: Sequence[float],
    *,
    n_bins: int = 10,
) -> float:
    """Population Stability Index between a baseline and a live sample.

    Bins are the baseline's quantile edges; ``PSI = sum (live_f - base_f) *
    ln(live_f / base_f)`` with a small floor on each fraction. Returns ``0.0``
    when the baseline has fewer than two distinct values (no basis to bin).
    """
    if not baseline or not live:
        return 0.0
    edges = _bin_edges(baseline, n_bins)
    if len(edges) <= 2:  # degenerate baseline (all one value)
        return 0.0
    base_f = _fractions(baseline, edges)
    live_f = _fractions(live, edges)
    psi = 0.0
    for bf, lf in zip(base_f, live_f, strict=True):
        bf = max(bf, _EPS)
        lf = max(lf, _EPS)
        psi += (lf - bf) * math.log(lf / bf)
    return psi


def _collect(
    window: Sequence[Mapping[str, Any]],
    feature_names: Sequence[str],
    model: ConditionModel | None,
) -> dict[str, list[float]]:
    """Extract per-feature value lists (and score list) from a window."""
    columns: dict[str, list[float]] = {name: [] for name in feature_names}
    if model is not None:
        columns[SCORE_FEATURE] = []
    for record in window:
        features = record.get("features") if isinstance(record.get("features"), Mapping) else record
        for name in feature_names:
            if name in features and features[name] is not None:
                columns[name].append(float(features[name]))
        if model is not None:
            columns[SCORE_FEATURE].append(model.score(features).score)
    return columns


def monitor_drift(
    baseline: Sequence[Mapping[str, Any]],
    live: Sequence[Mapping[str, Any]],
    *,
    feature_names: Sequence[str] | None = None,
    model: ConditionModel | None = None,
    psi_threshold: float = DEFAULT_PSI_THRESHOLD,
    n_bins: int = 10,
) -> DriftResult:
    """Compare live feature/score distributions to a baseline window.

    Args:
        baseline: The frozen reference window of records (each a feature mapping
            or a record with a ``"features"`` key).
        live: The current window to test for drift.
        feature_names: Features to monitor; defaults to ``model.spec`` features
            when a model is given, else the keys of the first baseline record.
        model: Optional model; when supplied its **score distribution** is
            monitored too (under :data:`SCORE_FEATURE`).
        psi_threshold: PSI value above which a feature is flagged as drifted.
        n_bins: Number of quantile bins for the PSI calculation.

    Returns:
        A :class:`DriftResult` whose ``drift_flag`` is ``True`` when any
        monitored feature (or the score distribution) exceeds ``psi_threshold``.

    Raises:
        ValueError: If either window is empty or no features can be resolved.
    """
    if not baseline or not live:
        raise ValueError("baseline and live windows must both be non-empty.")

    if feature_names is None:
        if model is not None:
            feature_names = model.spec.feature_names()
        else:
            first = baseline[0]
            src = first.get("features") if isinstance(first.get("features"), Mapping) else first
            feature_names = list(src.keys())
    if not feature_names:
        raise ValueError("no features to monitor; pass feature_names or a model.")

    base_cols = _collect(baseline, feature_names, model)
    live_cols = _collect(live, feature_names, model)

    results: list[FeatureDrift] = []
    drifted: list[str] = []
    max_psi = 0.0
    for name in base_cols:
        b_vals = base_cols[name]
        l_vals = live_cols.get(name, [])
        if not b_vals or not l_vals:
            continue
        psi = population_stability_index(b_vals, l_vals, n_bins=n_bins)
        b_mean = _mean(b_vals)
        b_std = _std(b_vals, b_mean)
        l_mean = _mean(l_vals)
        mean_shift = l_mean - b_mean
        z_shift = mean_shift / b_std if b_std > 0 else 0.0
        is_drift = psi >= psi_threshold
        if is_drift:
            drifted.append(name)
        max_psi = max(max_psi, psi)
        results.append(
            FeatureDrift(
                feature=name,
                psi=round(psi, 4),
                baseline_mean=round(b_mean, 4),
                baseline_std=round(b_std, 4),
                live_mean=round(l_mean, 4),
                mean_shift=round(mean_shift, 4),
                z_shift=round(z_shift, 4),
                drift=is_drift,
            )
        )

    return DriftResult(
        drift_flag=bool(drifted),
        max_psi=round(max_psi, 4),
        psi_threshold=psi_threshold,
        baseline_window=len(baseline),
        live_window=len(live),
        features=results,
        drifted_features=drifted,
    )
