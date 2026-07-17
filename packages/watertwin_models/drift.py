"""D1 drift hook: population-stability-index feature-drift monitoring.

A D1 model is trained/tuned against a baseline operating distribution. When the
live input distribution moves away from that baseline the model's preliminary
thresholds may no longer hold, so every D1 model exposes a **drift hook**: a
:class:`FeatureDriftMonitor` seeded with baseline reference samples that scores a
current batch with the population stability index (PSI) per feature and reports a
stable / watch / drift status against the model's PSI bands.

Pure and deterministic; no I/O. Drift bands are preliminary screening defaults
pending customer calibration.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from canonical_water_model import DataProvenance


def population_stability_index(
    baseline: list[float],
    current: list[float],
    bins: int = 10,
) -> float:
    """Population Stability Index between a baseline and a current sample.

    PSI quantifies how much a distribution has shifted. Conventional screening
    bands (preliminary): ``< 0.10`` stable, ``0.10-0.25`` moderate shift,
    ``> 0.25`` significant drift. Quantile bin edges are taken from the baseline;
    a small epsilon floor avoids ``log(0)`` for empty bins.

    Args:
        baseline: Baseline reference values for one feature.
        current: Current-batch values for the same feature.
        bins: Number of quantile bins (default 10).

    Returns:
        The PSI (>= 0). ``0.0`` when either sample is empty.

    Raises:
        ValueError: If ``bins`` is not positive.
    """
    if bins <= 0:
        raise ValueError("bins must be positive.")
    if not baseline or not current:
        return 0.0

    ordered = sorted(baseline)
    n = len(ordered)
    # Quantile edges from the baseline (interior edges only).
    edges: list[float] = []
    for i in range(1, bins):
        pos = i / bins * (n - 1)
        lo = int(math.floor(pos))
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        edges.append(ordered[lo] * (1 - frac) + ordered[hi] * frac)

    def _distribution(values: list[float]) -> list[float]:
        counts = [0] * bins
        for v in values:
            idx = 0
            while idx < len(edges) and v > edges[idx]:
                idx += 1
            counts[idx] += 1
        total = len(values)
        return [c / total for c in counts]

    eps = 1e-6
    base_dist = _distribution(baseline)
    cur_dist = _distribution(current)
    psi = 0.0
    for b, c in zip(base_dist, cur_dist, strict=True):
        b = max(b, eps)
        c = max(c, eps)
        psi += (c - b) * math.log(c / b)
    return round(psi, 6)


class DriftReport(BaseModel):
    """Per-feature PSI drift report against the model baseline (preliminary)."""

    model_config = {"protected_namespaces": ()}

    model_id: str
    method: str = "population_stability_index"
    psi_by_feature: dict[str, float] = Field(default_factory=dict)
    max_psi: float = 0.0
    driven_by: str | None = None
    status: str = "stable"  # "stable" | "watch" | "drift"
    warn_psi: float = 0.10
    alert_psi: float = 0.25
    provenance: DataProvenance = DataProvenance.preliminary
    pending_customer_calibration: bool = True


class FeatureDriftMonitor:
    """A drift hook seeded with baseline reference samples.

    :meth:`check` scores a current batch (a mapping of feature -> list of values)
    with per-feature PSI against the baseline and reports the worst-case status.
    """

    def __init__(
        self,
        model_id: str,
        baseline: dict[str, list[float]],
        warn_psi: float = 0.10,
        alert_psi: float = 0.25,
        bins: int = 10,
    ) -> None:
        if warn_psi < 0 or alert_psi < 0:
            raise ValueError("PSI bands must be non-negative.")
        if alert_psi < warn_psi:
            raise ValueError("alert_psi must be >= warn_psi.")
        self.model_id = model_id
        self.baseline = {k: list(v) for k, v in baseline.items()}
        self.warn_psi = warn_psi
        self.alert_psi = alert_psi
        self.bins = bins

    def check(self, current: dict[str, list[float]]) -> DriftReport:
        """Score a current batch against the baseline and report drift status."""
        psi_by_feature: dict[str, float] = {}
        for feature, base_values in self.baseline.items():
            cur_values = current.get(feature)
            if not cur_values:
                continue
            psi_by_feature[feature] = population_stability_index(
                base_values, cur_values, bins=self.bins
            )

        max_psi = 0.0
        driven_by: str | None = None
        for feature, psi in psi_by_feature.items():
            if psi > max_psi:
                max_psi = psi
                driven_by = feature

        if max_psi >= self.alert_psi:
            status = "drift"
        elif max_psi >= self.warn_psi:
            status = "watch"
        else:
            status = "stable"

        return DriftReport(
            model_id=self.model_id,
            psi_by_feature=psi_by_feature,
            max_psi=round(max_psi, 6),
            driven_by=driven_by,
            status=status,
            warn_psi=self.warn_psi,
            alert_psi=self.alert_psi,
        )
