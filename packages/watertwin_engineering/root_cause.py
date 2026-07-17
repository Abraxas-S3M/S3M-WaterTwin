"""Deterministic causal root-cause ranking for water-treatment assets.

This module generalizes the platform's high-pressure-pump (HPP) fault-assessment
logic into a transparent, evidence-weighted root-cause ranker. Given an
observed symptom pattern (e.g. rising power with falling production) plus
corroborating context signals -- water-quality indicators, pump-curve deviation,
feed-salinity trend, valve feedback and cross-sensor consistency -- it returns an
ordered list of candidate causes whose probabilities sum to ``~1.0``. Each cause
carries a plain-language ``evidence`` string citing the signal that supports it.

Like the rest of :mod:`watertwin_engineering` every function here is pure and
deterministic. The ranking is an **advisory, preliminary** diagnostic aid, not a
validated fault diagnosis.

Canonical worked example (reproducible in tests): for a high-pressure pump whose
electrical power is up ``+11%`` while product-water production is down ``-6%``,
with elevated water-quality fouling signals, the ranker orders the causes:

    membrane fouling > pump-efficiency loss > feed-salinity rise
        > valve restriction > sensor error
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

PRELIMINARY = "preliminary"

#: Candidate causes considered by the ranker, in canonical display order.
CAUSES: tuple[str, ...] = (
    "membrane_fouling",
    "pump_efficiency_loss",
    "feed_salinity_rise",
    "valve_restriction",
    "sensor_error",
)

#: Human-readable labels for each candidate cause.
CAUSE_LABELS: dict[str, str] = {
    "membrane_fouling": "Membrane fouling",
    "pump_efficiency_loss": "Pump efficiency loss",
    "feed_salinity_rise": "Feed salinity rise",
    "valve_restriction": "Valve restriction",
    "sensor_error": "Sensor error",
}

#: Small non-zero floor per cause so the ranking is well-posed even when few
#: evidence signals are present (documented defaults, not tuning parameters).
_BASE: dict[str, float] = {
    "membrane_fouling": 0.5,
    "pump_efficiency_loss": 0.5,
    "feed_salinity_rise": 0.5,
    "valve_restriction": 0.5,
    "sensor_error": 1.0,
}

__all__ = [
    "PRELIMINARY",
    "CAUSES",
    "CAUSE_LABELS",
    "RootCause",
    "root_cause_rank",
]


@dataclass(frozen=True)
class RootCause:
    """One ranked candidate cause with its probability and supporting evidence."""

    cause: str
    label: str
    probability: float
    evidence: str


def _num(source: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = source.get(key, default)
    if value is None:
        return default
    return float(value)


def root_cause_rank(
    asset: Mapping[str, Any],
    telemetry: Mapping[str, Any],
    context: Optional[Mapping[str, Any]] = None,
) -> list[RootCause]:
    """Rank probable root causes for an observed symptom pattern.

    Generalizes the HPP fault-assessment logic: each candidate cause accrues an
    evidence-weighted score from the symptom pattern in ``telemetry`` and the
    corroborating signals in ``context``, then the scores are normalized so the
    returned probabilities sum to ``~1.0``. The result is sorted most-probable
    first.

    ``telemetry`` (all optional, **percent** deltas vs the recent baseline):

    * ``power_pct_change`` -- electrical power change, ``%`` (positive = up).
    * ``production_pct_change`` -- product-water production change, ``%``
      (negative = down).

    ``context`` (all optional; corroborating evidence in the noted units):

    * ``normalized_dp_rise_pct`` -- normalized differential-pressure rise, ``%``
      (water-quality/fouling signal).
    * ``normalized_salt_passage_rise_pct`` -- normalized salt-passage rise, ``%``
      (water-quality/membrane-integrity signal).
    * ``pump_curve_efficiency_deviation_pct`` -- operating point below the pump
      efficiency curve, ``%`` (curve-deviation evidence).
    * ``feed_salinity_rise_pct`` -- feed conductivity/salinity rise, ``%``
      (raises osmotic demand).
    * ``valve_position_error_pct`` -- valve command-vs-feedback error, ``%``.
    * ``sensor_consistency`` -- cross-sensor agreement in ``[0, 1]`` (``1`` =
      fully consistent; lower raises the sensor-error hypothesis).
    * ``last_cip_days`` / ``days_since_pump_service`` /
      ``days_since_calibration`` -- maintenance-history context woven into the
      evidence strings.

    Args:
        asset: Asset descriptor (uses ``asset_id`` / ``asset_type`` for
            evidence text only).
        telemetry: Observed symptom deltas (percent).
        context: Corroborating evidence signals.

    Returns:
        A list of :class:`RootCause`, most-probable first, whose probabilities
        sum to ``~1.0``.

    Raises:
        ValueError: If ``telemetry`` is not a mapping.
    """
    if not isinstance(telemetry, Mapping):
        raise ValueError("telemetry must be a mapping of signal -> value.")
    ctx: Mapping[str, Any] = context or {}
    asset_id = str(asset.get("asset_id", "asset")) if isinstance(asset, Mapping) else "asset"

    power = max(0.0, _num(telemetry, "power_pct_change"))
    prod_drop = max(0.0, -_num(telemetry, "production_pct_change"))

    dp_rise = max(0.0, _num(ctx, "normalized_dp_rise_pct"))
    sp_rise = max(0.0, _num(ctx, "normalized_salt_passage_rise_pct"))
    curve_dev = max(0.0, _num(ctx, "pump_curve_efficiency_deviation_pct"))
    salinity_rise = max(0.0, _num(ctx, "feed_salinity_rise_pct"))
    valve_err = max(0.0, _num(ctx, "valve_position_error_pct"))
    sensor_consistency = _num(ctx, "sensor_consistency", 1.0)
    sensor_inconsistency = max(0.0, 1.0 - sensor_consistency)

    last_cip = _num(ctx, "last_cip_days", 0.0)
    pump_service = _num(ctx, "days_since_pump_service", 0.0)
    calibration = _num(ctx, "days_since_calibration", 0.0)

    # --- Evidence-weighted scores (see module docstring for the rationale). ---
    scores: dict[str, float] = {
        "membrane_fouling": _BASE["membrane_fouling"]
        + 0.8 * power
        + 1.2 * prod_drop
        + 0.6 * dp_rise
        + 0.5 * sp_rise,
        "pump_efficiency_loss": _BASE["pump_efficiency_loss"]
        + 1.0 * power
        + 1.2 * curve_dev,
        "feed_salinity_rise": _BASE["feed_salinity_rise"]
        + 0.5 * power
        + 0.6 * prod_drop
        + 1.0 * salinity_rise,
        "valve_restriction": _BASE["valve_restriction"]
        + 0.4 * power
        + 2.0 * valve_err,
        "sensor_error": _BASE["sensor_error"] + 20.0 * sensor_inconsistency,
    }

    total = sum(scores.values()) or 1.0
    probabilities = {cause: score / total for cause, score in scores.items()}

    evidence: dict[str, str] = {
        "membrane_fouling": (
            f"WQ signal: normalized dP +{dp_rise:.0f}% and salt passage "
            f"+{sp_rise:.0f}% vs baseline; power +{power:.0f}% with production "
            f"-{prod_drop:.0f}% (last CIP {last_cip:.0f} d ago)."
        ),
        "pump_efficiency_loss": (
            f"Curve deviation: {asset_id} operating point {curve_dev:.0f}% below "
            f"the pump efficiency curve at +{power:.0f}% power "
            f"({pump_service:.0f} d since pump service)."
        ),
        "feed_salinity_rise": (
            f"Sensor value: feed salinity/conductivity +{salinity_rise:.0f}% "
            f"raises osmotic demand, consistent with production -{prod_drop:.0f}%."
        ),
        "valve_restriction": (
            f"Sensor value: valve position command-vs-feedback error "
            f"{valve_err:.0f}%; throttling adds differential pressure and power."
        ),
        "sensor_error": (
            f"Historical comparison: cross-sensor consistency "
            f"{sensor_consistency * 100:.0f}% "
            f"({calibration:.0f} d since last calibration)."
        ),
    }

    ranked = [
        RootCause(
            cause=cause,
            label=CAUSE_LABELS[cause],
            probability=round(probabilities[cause], 4),
            evidence=evidence[cause],
        )
        for cause in CAUSES
    ]
    ranked.sort(key=lambda rc: rc.probability, reverse=True)
    return ranked
