"""Cyber-Physical Security analytics (advisory, read-only).

This module surfaces the platform's existing cyber-physical + anomaly signals as
a security posture view. It introduces **no new physics and no control path**: it
reads the synthetic/OT telemetry the platform already ingests and the design
limits the plant model already declares, then derives four read-only views:

* **Sensor-confidence scoring** — per-asset trust in the instrument feed, from
  cross-sensor consistency, calibration age and the fraction of telemetry that
  sits outside its physical envelope.
* **Cyber-physical consistency detection** — compares observed telemetry against
  the plant's *hydraulic / physical design expectation* (rated limits, clean
  baselines, transfer-efficiency ratings). A reading that contradicts the
  physical expectation (e.g. a value beyond its design bound) is a cyber-physical
  inconsistency worth investigating (stuck/spoofed sensor, drift, or a genuine
  excursion).
* **Source-health** — the active telemetry source, any fallback to synthetic,
  and feed freshness/quality.
* **Audit-chain integrity** — folds in the tamper-evident audit hash-chain verify
  status (see :mod:`app.audit`).

Every figure is advisory and preliminary on a synthetic basis; nothing here is a
validated security determination and nothing writes to any control system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from . import predictive_maintenance as pdm

#: Consistency-score band thresholds (higher = telemetry agrees with physics).
CONSISTENT_THRESHOLD = 0.9
DEVIATION_THRESHOLD = 0.7

#: Sensor-confidence band thresholds.
CONFIDENCE_HIGH = 0.85
CONFIDENCE_MEDIUM = 0.6

#: Minimum acceptable fraction of a device's rated transfer efficiency before the
#: reading is treated as physically inconsistent (5% design tolerance).
_EFFICIENCY_TOLERANCE = 0.05

#: Maximum plausible normalized differential pressure for a clean-ish filter
#: bank before the reading contradicts the hydraulic expectation.
_MAX_NORMALIZED_DP = 2.5


@dataclass(frozen=True)
class _MaxBound:
    """A telemetry metric that must stay at or below a design limit."""

    metric: str
    limit_metric: str
    basis: str


@dataclass(frozen=True)
class _MinBound:
    """A telemetry metric that must stay at or above a rated design value."""

    metric: str
    rated_metric: str
    tolerance: float
    basis: str


# Physically-grounded checks derived from the plant model's own design limits.
# These encode the "hydraulic / physical expectation" each observed reading is
# compared against for cyber-physical consistency detection.
_MAX_BOUNDS: tuple[_MaxBound, ...] = (
    _MaxBound("vibration_mm_s", "vibration_limit_mm_s", "ISO 10816 vibration design limit"),
    _MaxBound("bearing_temp_c", "bearing_temp_limit_c", "bearing thermal design limit"),
    _MaxBound("winding_temp_c", "winding_temp_limit_c", "motor winding insulation limit"),
)
_MIN_BOUNDS: tuple[_MinBound, ...] = (
    _MinBound(
        "transfer_efficiency_pct",
        "rated_transfer_efficiency_pct",
        _EFFICIENCY_TOLERANCE,
        "ERD rated transfer-efficiency (hydraulic recovery expectation)",
    ),
)


def _band(score: float, high: float, medium: float) -> str:
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    return "low"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


# --------------------------------------------------------------------------- #
# Cyber-physical consistency (telemetry vs. hydraulic/physical expectation)
# --------------------------------------------------------------------------- #


def _consistency_checks(telemetry: dict[str, float]) -> list[dict[str, Any]]:
    """Compare observed telemetry against the plant's physical expectations.

    Returns one check per metric that has a declared design expectation. Each
    check records the observed value, the expected bound, the signed residual as
    a percentage of the bound, and whether the reading is physically consistent.
    """
    checks: list[dict[str, Any]] = []

    for rule in _MAX_BOUNDS:
        if rule.metric not in telemetry or rule.limit_metric not in telemetry:
            continue
        observed = float(telemetry[rule.metric])
        limit = float(telemetry[rule.limit_metric])
        if limit <= 0:
            continue
        exceed = observed - limit
        residual_pct = max(0.0, exceed / limit) * 100.0
        checks.append(
            {
                "metric": rule.metric,
                "observed": round(observed, 4),
                "expected_bound": round(limit, 4),
                "bound": "max",
                "residual_pct": round(residual_pct, 2),
                "consistent": observed <= limit,
                "basis": rule.basis,
            }
        )

    for rule in _MIN_BOUNDS:
        if rule.metric not in telemetry or rule.rated_metric not in telemetry:
            continue
        observed = float(telemetry[rule.metric])
        rated = float(telemetry[rule.rated_metric])
        if rated <= 0:
            continue
        floor = rated * (1.0 - rule.tolerance)
        shortfall = floor - observed
        residual_pct = max(0.0, shortfall / rated) * 100.0
        checks.append(
            {
                "metric": rule.metric,
                "observed": round(observed, 4),
                "expected_bound": round(floor, 4),
                "bound": "min",
                "residual_pct": round(residual_pct, 2),
                "consistent": observed >= floor,
                "basis": rule.basis,
            }
        )

    # Filter differential pressure: normalized dP contradicts the clean-baseline
    # hydraulic expectation when it climbs well above the clean value.
    if "normalized_dp" in telemetry:
        observed = float(telemetry["normalized_dp"])
        residual_pct = max(0.0, (observed - _MAX_NORMALIZED_DP) / _MAX_NORMALIZED_DP) * 100.0
        checks.append(
            {
                "metric": "normalized_dp",
                "observed": round(observed, 4),
                "expected_bound": _MAX_NORMALIZED_DP,
                "bound": "max",
                "residual_pct": round(residual_pct, 2),
                "consistent": observed <= _MAX_NORMALIZED_DP,
                "basis": "clean-baseline differential-pressure ratio",
            }
        )

    return checks


def _consistency_for_asset(spec: pdm.AssetSpec) -> dict[str, Any]:
    checks = _consistency_checks(spec.telemetry)
    # The consistency score penalises the mean physical residual across checks
    # (capped at one bound-width per check), so a single gross excursion cannot
    # be masked by many nominal readings.
    if checks:
        penalty = sum(min(1.0, c["residual_pct"] / 100.0) for c in checks) / len(checks)
    else:
        penalty = 0.0
    score = round(_clamp(1.0 - penalty), 4)
    inconsistent = [c for c in checks if not c["consistent"]]
    if score >= CONSISTENT_THRESHOLD and not inconsistent:
        status = "consistent"
    elif score >= DEVIATION_THRESHOLD:
        status = "deviation"
    else:
        status = "inconsistent"
    return {
        "asset_id": spec.asset_id,
        "asset_name": spec.name,
        "consistency_score": score,
        "status": status,
        "checks": checks,
        "inconsistent_metrics": [c["metric"] for c in inconsistent],
    }


def cyber_physical_consistency() -> list[dict[str, Any]]:
    """Per-asset cyber-physical consistency (telemetry vs. physical expectation).

    Assets are ordered least-consistent first so the highest-attention items
    surface at the top of the security view.
    """
    rows = [_consistency_for_asset(spec) for spec in pdm.ASSETS.values()]
    rows.sort(key=lambda r: r["consistency_score"])
    return rows


# --------------------------------------------------------------------------- #
# Sensor-confidence scoring
# --------------------------------------------------------------------------- #


def _sensor_confidence_for_asset(
    spec: pdm.AssetSpec, consistency: dict[str, Any]
) -> dict[str, Any]:
    ctx = spec.root_cause_context or {}
    cross_sensor = float(ctx.get("sensor_consistency", 1.0))
    calibration_days = float(ctx.get("days_since_calibration", 0.0))

    # Calibration ages the feed's trustworthiness; ~180 days fully erodes the
    # calibration component (documented default, not a tuned parameter).
    calibration_factor = _clamp(1.0 - calibration_days / 180.0)

    checks = consistency.get("checks", [])
    if checks:
        within = sum(1 for c in checks if c["consistent"]) / len(checks)
    else:
        within = 1.0

    # Weighted blend: cross-sensor agreement dominates, corroborated by physical
    # plausibility and calibration recency.
    confidence = round(
        _clamp(0.5 * cross_sensor + 0.3 * within + 0.2 * calibration_factor), 4
    )
    return {
        "asset_id": spec.asset_id,
        "asset_name": spec.name,
        "confidence": confidence,
        "band": _band(confidence, CONFIDENCE_HIGH, CONFIDENCE_MEDIUM),
        "cross_sensor_consistency": round(cross_sensor, 4),
        "physical_plausibility": round(within, 4),
        "calibration_days": round(calibration_days, 1),
    }


def sensor_confidence(
    consistency: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Per-asset sensor-confidence scores, lowest-confidence first."""
    consistency = consistency if consistency is not None else cyber_physical_consistency()
    by_asset = {row["asset_id"]: row for row in consistency}
    rows = [
        _sensor_confidence_for_asset(spec, by_asset.get(spec.asset_id, {}))
        for spec in pdm.ASSETS.values()
    ]
    rows.sort(key=lambda r: r["confidence"])
    return rows


# --------------------------------------------------------------------------- #
# Source health
# --------------------------------------------------------------------------- #


def source_health(resolution: Any, *, reading_count: Optional[int] = None) -> dict[str, Any]:
    """Summarise telemetry-source health from a :class:`SourceResolution`.

    ``fallback`` (a configured OT source was unreachable and the platform is
    running on synthetic telemetry) degrades the health status; otherwise the
    feed is healthy. Never raises — a resolver hiccup reports ``unknown``.
    """
    try:
        described = resolution.describe()
    except Exception as exc:  # defensive: the resolver should not raise
        return {"status": "unknown", "error": str(exc)}

    fallback = bool(described.get("fallback"))
    status = "degraded" if fallback else "healthy"
    return {
        "status": status,
        "active_source": described.get("active_source"),
        "requested_source": described.get("requested_source"),
        "fallback": fallback,
        "fallback_reason": described.get("fallback_reason"),
        "available_sources": described.get("available_sources", []),
        "detail": described.get("detail", {}),
        "reading_count": reading_count,
    }


# --------------------------------------------------------------------------- #
# Overall posture
# --------------------------------------------------------------------------- #


def overall_status(
    *,
    audit_ok: bool,
    source_status: str,
    consistency: list[dict[str, Any]],
    confidence: list[dict[str, Any]],
) -> str:
    """Roll the four views up into a single posture: ok | attention | alert.

    A broken audit chain is always an ``alert`` (integrity is non-negotiable);
    any inconsistent telemetry or low sensor confidence raises ``attention``.
    """
    if not audit_ok:
        return "alert"
    if any(row["status"] == "inconsistent" for row in consistency):
        return "alert"
    degraded = (
        source_status != "healthy"
        or any(row["status"] == "deviation" for row in consistency)
        or any(row["band"] == "low" for row in confidence)
    )
    return "attention" if degraded else "ok"
