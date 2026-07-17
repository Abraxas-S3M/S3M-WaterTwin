"""Health scoring and anomaly detection over telemetry."""

from __future__ import annotations

import statistics
from datetime import UTC, datetime

from .boundary import current_boundary
from .models import AnomalyResult, HealthScore, TelemetryReading
from .plant import MetricSpec


def _metric_penalty(spec: MetricSpec, value: float) -> float:
    """Return a 0..1 penalty for how far ``value`` breaches the spec thresholds."""

    if spec.higher_is_worse:
        if value <= spec.warn:
            return 0.0
        if value >= spec.crit:
            return 1.0
        return (value - spec.warn) / (spec.crit - spec.warn)
    # lower_is_worse
    if value >= spec.warn:
        return 0.0
    if value <= spec.crit:
        return 1.0
    return (spec.warn - value) / (spec.warn - spec.crit)


def _status_for(score: float) -> str:
    if score >= 85.0:
        return "healthy"
    if score >= 70.0:
        return "watch"
    if score >= 50.0:
        return "degraded"
    return "critical"


def compute_health(
    asset_id: str, reading: TelemetryReading | None, specs: list[MetricSpec]
) -> HealthScore:
    factors: dict[str, float] = {}
    if reading is None or not specs:
        return HealthScore(
            asset_id=asset_id,
            score=100.0,
            status="healthy",
            factors={},
            computed_at=datetime.now(UTC),
            control_boundary=current_boundary(),
        )

    penalties: list[float] = []
    for spec in specs:
        if spec.name not in reading.metrics:
            continue
        penalty = _metric_penalty(spec, reading.metrics[spec.name])
        factors[spec.name] = round(1.0 - penalty, 4)
        penalties.append(penalty)

    if penalties:
        # Weight the worst offenders more heavily than the average.
        avg = sum(penalties) / len(penalties)
        worst = max(penalties)
        aggregate = 0.5 * avg + 0.5 * worst
    else:
        aggregate = 0.0

    score = round(max(0.0, 100.0 * (1.0 - aggregate)), 2)
    return HealthScore(
        asset_id=asset_id,
        score=score,
        status=_status_for(score),
        factors=factors,
        computed_at=datetime.now(UTC),
        control_boundary=current_boundary(),
    )


def _pick_metric(specs: list[MetricSpec]) -> MetricSpec | None:
    for spec in specs:
        if spec.degradable and spec.higher_is_worse:
            return spec
    for spec in specs:
        if spec.higher_is_worse:
            return spec
    return specs[0] if specs else None


def compute_anomaly(
    asset_id: str,
    history: list[TelemetryReading],
    specs: list[MetricSpec],
    threshold: float = 3.0,
) -> AnomalyResult:
    spec = _pick_metric(specs)
    now = datetime.now(UTC)
    boundary = current_boundary()

    if spec is None or len(history) < 8:
        return AnomalyResult(
            asset_id=asset_id,
            is_anomaly=False,
            score=0.0,
            method="zscore",
            metric=spec.name if spec else None,
            details={"reason": "insufficient_history", "samples": len(history)},
            computed_at=now,
            control_boundary=boundary,
        )

    series = [r.metrics[spec.name] for r in history if spec.name in r.metrics]
    if len(series) < 8:
        return AnomalyResult(
            asset_id=asset_id,
            is_anomaly=False,
            score=0.0,
            method="zscore",
            metric=spec.name,
            details={"reason": "insufficient_metric_samples", "samples": len(series)},
            computed_at=now,
            control_boundary=boundary,
        )

    baseline = series[:-1]
    current = series[-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    if stdev == 0.0:
        z = 0.0
    else:
        z = (current - mean) / stdev

    return AnomalyResult(
        asset_id=asset_id,
        is_anomaly=abs(z) >= threshold,
        score=round(abs(z), 3),
        method="zscore",
        metric=spec.name,
        details={
            "current": round(current, 4),
            "mean": round(mean, 4),
            "stdev": round(stdev, 4),
            "threshold": threshold,
        },
        computed_at=now,
        control_boundary=boundary,
    )
