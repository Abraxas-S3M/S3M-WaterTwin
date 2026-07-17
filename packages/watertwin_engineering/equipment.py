"""Deterministic equipment-health and predictive-maintenance physics.

This module extends the single canonical physics engine
(:mod:`watertwin_engineering`) with the component-level health, operating-
envelope, remaining-useful-life (RUL), failure-probability and maintenance-
prioritization math used by the Equipment & Membrane Intelligence and
Predictive Maintenance capabilities.

Like the rest of the package every function here is **pure and deterministic**:
it performs no I/O and, given the same inputs, always returns the same outputs.
Results are returned as small frozen dataclasses so the API/canonical layers can
map them onto the canonical Pydantic models.

Everything here is **advisory and preliminary**. Health scores follow the same
*visible-penalty* pattern used elsewhere in the platform: a component starts at a
perfect ``100`` and every degradation signal subtracts a transparent, labelled
penalty (a :class:`HealthContribution`) so an operator can see exactly why a
component scored the way it did. Remaining-useful-life and failure-probability
estimates are screening-grade engineering approximations -- never validated
production predictions or guaranteed time-to-failure -- and every RUL/failure
result is stamped ``provenance = "preliminary"`` with an uncertainty band.

Units are stated explicitly in every signature.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Provenance marker attached to every forward-looking estimate. RUL and failure
#: probability are preliminary engineering estimates, not validated predictions.
PRELIMINARY = "preliminary"

#: Health-score band thresholds (mirrors ``canonical_water_model.HealthBand``).
#: A component at/above 90 is Healthy; below 40 is Critical.
_BAND_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (90.0, "Healthy"),
    (75.0, "Monitor"),
    (60.0, "Degraded"),
    (40.0, "HighRisk"),
)

#: The component types with a defined health model.
COMPONENT_TYPES: tuple[str, ...] = (
    "motor",
    "bearing",
    "seal",
    "vfd",
    "filter",
    "valve",
    "erd",
    "pump",
)

#: Default failure threshold (0-100 health) used when extrapolating a health
#: trend to end-of-life. A component is treated as "failed" once its health
#: score decays to this value (documented default, not a tuning parameter).
DEFAULT_FAILURE_THRESHOLD = 30.0

#: Failure-probability horizons (label -> days) evaluated by
#: :func:`failure_probability`.
FAILURE_HORIZON_DAYS: dict[str, float] = {
    "24h": 1.0,
    "7d": 7.0,
    "30d": 30.0,
    "90d": 90.0,
}

#: Baseline hazard multiplier per health band. Worse bands map to a higher base
#: hazard so failure probability is monotonic in health band.
_BAND_HAZARD_BASE: dict[str, float] = {
    "Healthy": 0.02,
    "Monitor": 0.06,
    "Degraded": 0.15,
    "HighRisk": 0.35,
    "Critical": 0.70,
}

__all__ = [
    "PRELIMINARY",
    "COMPONENT_TYPES",
    "DEFAULT_FAILURE_THRESHOLD",
    "FAILURE_HORIZON_DAYS",
    "HealthContribution",
    "ComponentHealthResult",
    "OperatingEnvelopeResult",
    "RemainingUsefulLifeResult",
    "FailureProbabilityResult",
    "MaintenancePriorityResult",
    "health_band",
    "component_health",
    "operating_envelope_score",
    "remaining_useful_life_days",
    "failure_probability",
    "maintenance_priority",
]


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthContribution:
    """One transparent penalty (or credit) applied to a health score.

    ``delta`` is the signed points change (negative = penalty), ``factor`` names
    the driver and ``detail`` explains the evidence (value vs limit).
    """

    factor: str
    delta: float
    detail: str


@dataclass(frozen=True)
class ComponentHealthResult:
    """Transparent 0-100 component health with a full contribution breakdown."""

    component_type: str
    score: float
    band: str
    contributions: list[HealthContribution] = field(default_factory=list)
    provenance: str = PRELIMINARY


@dataclass(frozen=True)
class OperatingEnvelopeResult:
    """Fractions of operating time spent in each envelope regime (0-1 each)."""

    samples: int
    at_bep_fraction: float
    low_flow_fraction: float
    high_pressure_fraction: float
    excess_temperature_fraction: float
    cavitation_risk_fraction: float
    provenance: str = PRELIMINARY


@dataclass(frozen=True)
class RemainingUsefulLifeResult:
    """Preliminary RUL ensemble estimate with an uncertainty band (days)."""

    rul_days: float
    lower_days: float
    upper_days: float
    method: str
    basis: list[str] = field(default_factory=list)
    provenance: str = PRELIMINARY


@dataclass(frozen=True)
class FailureProbabilityResult:
    """Monotonic failure-probability hazard mapped onto fixed horizons."""

    horizons: dict[str, float]
    provenance: str = PRELIMINARY


@dataclass(frozen=True)
class MaintenancePriorityResult:
    """Maintenance priority rank score (higher = more urgent)."""

    rank_score: float
    factors: dict[str, float] = field(default_factory=dict)
    provenance: str = PRELIMINARY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def health_band(score: float) -> str:
    """Map a 0-100 health score onto its band label."""
    for threshold, label in _BAND_THRESHOLDS:
        if score >= threshold:
            return label
    return "Critical"


def _get(telemetry: dict[str, float], key: str, default: float = 0.0) -> float:
    value = telemetry.get(key, default)
    if value is None:
        return default
    return float(value)


def _penalty(
    contributions: list[HealthContribution],
    factor: str,
    delta: float,
    detail: str,
) -> None:
    """Append a penalty only when it is material (avoids 0.0 noise rows)."""
    if abs(delta) >= 0.05:
        contributions.append(HealthContribution(factor=factor, delta=round(delta, 2), detail=detail))


def _excess_ratio(value: float, limit: float) -> float:
    """Fractional exceedance of ``value`` over ``limit`` (0 when within limit)."""
    if limit <= 0:
        return 0.0
    return max(0.0, (value - limit) / limit)


# ---------------------------------------------------------------------------
# Component health (visible-penalty pattern)
# ---------------------------------------------------------------------------


def _motor_penalties(t: dict[str, float], out: list[HealthContribution]) -> None:
    ci = _get(t, "current_imbalance_pct")
    if ci > 0:
        # NEMA MG-1 guidance: derate above ~1% current imbalance; 10% is severe.
        _penalty(out, "Current imbalance", -min(22.0, 2.2 * ci),
                 f"{ci:.1f}% phase current imbalance (limit ~1%)")
    vi = _get(t, "voltage_imbalance_pct")
    if vi > 0:
        _penalty(out, "Voltage imbalance", -min(18.0, 3.0 * vi),
                 f"{vi:.1f}% supply voltage imbalance (limit ~1%)")
    wt = _get(t, "winding_temp_c")
    wt_limit = _get(t, "winding_temp_limit_c", 155.0)
    ex = _excess_ratio(wt, wt_limit)
    if ex > 0:
        _penalty(out, "Winding temperature", -min(30.0, 200.0 * ex),
                 f"{wt:.0f} C winding vs {wt_limit:.0f} C insulation limit")
    vib = _get(t, "vibration_mm_s")
    vib_limit = _get(t, "vibration_limit_mm_s", 4.5)
    ex = _excess_ratio(vib, vib_limit)
    if ex > 0:
        _penalty(out, "Vibration", -min(28.0, 45.0 * ex),
                 f"{vib:.1f} mm/s RMS vs {vib_limit:.1f} mm/s (ISO 10816)")


def _bearing_penalties(t: dict[str, float], out: list[HealthContribution]) -> None:
    bt = _get(t, "bearing_temp_c")
    bt_limit = _get(t, "bearing_temp_limit_c", 90.0)
    ex = _excess_ratio(bt, bt_limit)
    if ex > 0:
        _penalty(out, "Bearing temperature", -min(35.0, 220.0 * ex),
                 f"{bt:.0f} C bearing vs {bt_limit:.0f} C alarm limit")
    vib = _get(t, "vibration_mm_s")
    vib_limit = _get(t, "vibration_limit_mm_s", 4.5)
    ex = _excess_ratio(vib, vib_limit)
    if ex > 0:
        _penalty(out, "Vibration", -min(35.0, 55.0 * ex),
                 f"{vib:.1f} mm/s RMS vs {vib_limit:.1f} mm/s (ISO 10816)")


def _seal_penalties(t: dict[str, float], out: list[HealthContribution]) -> None:
    leak = _get(t, "seal_leakage_ml_min")
    leak_limit = _get(t, "seal_leakage_limit_ml_min", 5.0)
    ex = _excess_ratio(leak, leak_limit)
    if ex > 0:
        _penalty(out, "Seal leakage", -min(45.0, 30.0 * ex),
                 f"{leak:.1f} mL/min leakage vs {leak_limit:.1f} mL/min limit")


def _vfd_penalties(t: dict[str, float], out: list[HealthContribution]) -> None:
    faults = _get(t, "vfd_fault_count")
    if faults > 0:
        _penalty(out, "VFD faults", -min(30.0, 8.0 * faults),
                 f"{faults:.0f} drive fault/trip event(s) in window")
    thd = _get(t, "thd_pct")
    thd_limit = _get(t, "thd_limit_pct", 5.0)  # IEEE 519 voltage THD guidance
    ex = _excess_ratio(thd, thd_limit)
    if ex > 0:
        _penalty(out, "Harmonic distortion", -min(20.0, 25.0 * ex),
                 f"{thd:.1f}% THD vs {thd_limit:.1f}% (IEEE 519)")


def _filter_penalties(t: dict[str, float], out: list[HealthContribution]) -> None:
    # Prefer a pre-normalized dP ratio (dP / clean dP); else derive from dp/clean.
    ndp = t.get("normalized_dp")
    if ndp is None:
        dp = _get(t, "dp_bar")
        clean = _get(t, "clean_dp_bar", 0.3)
        ndp = dp / clean if clean > 0 else 1.0
    ndp = float(ndp)
    # Cartridge-filter change-out is typically at ~2-3x clean dP.
    if ndp > 1.0:
        _penalty(out, "Differential pressure", -min(55.0, 32.0 * (ndp - 1.0)),
                 f"normalized dP {ndp:.2f}x clean (change-out ~2-3x)")


def _valve_penalties(t: dict[str, float], out: list[HealthContribution]) -> None:
    pos_err = _get(t, "position_error_pct")
    if pos_err > 0:
        _penalty(out, "Position error", -min(35.0, 3.0 * pos_err),
                 f"{pos_err:.1f}% deviation between command and feedback")
    travel = _get(t, "travel_deviation_pct")
    if travel > 0:
        _penalty(out, "Travel/stiction", -min(25.0, 2.0 * travel),
                 f"{travel:.1f}% travel deviation (stiction/hysteresis)")


def _erd_penalties(t: dict[str, float], out: list[HealthContribution]) -> None:
    eff = _get(t, "transfer_efficiency_pct")
    rated = _get(t, "rated_transfer_efficiency_pct", 96.0)
    if eff > 0 and eff < rated:
        drop = rated - eff
        _penalty(out, "Transfer efficiency", -min(50.0, 4.0 * drop),
                 f"{eff:.1f}% transfer efficiency vs {rated:.1f}% rated")


def _pump_penalties(t: dict[str, float], out: list[HealthContribution]) -> None:
    """Pump health reuses the motor + bearing + seal degradation signals plus a
    hydraulic-efficiency-drift term, rather than re-deriving pump hydraulics
    (those live in :mod:`watertwin_engineering.ro`/``calculations``)."""
    _motor_penalties(t, out)
    _bearing_penalties(t, out)
    _seal_penalties(t, out)
    eff_drift = _get(t, "efficiency_drift_pct")
    if eff_drift > 0:
        _penalty(out, "Efficiency drift", -min(25.0, 2.0 * eff_drift),
                 f"{eff_drift:.1f}% hydraulic efficiency below commissioning baseline")


_COMPONENT_PENALTY_FN = {
    "motor": _motor_penalties,
    "bearing": _bearing_penalties,
    "seal": _seal_penalties,
    "vfd": _vfd_penalties,
    "filter": _filter_penalties,
    "valve": _valve_penalties,
    "erd": _erd_penalties,
    "pump": _pump_penalties,
}


def component_health(component_type: str, telemetry: dict[str, float]) -> ComponentHealthResult:
    """Transparent component health score in ``[0, 100]`` with a breakdown.

    Uses the same visible-penalty pattern as the platform's pump-health scoring:
    a component begins at a perfect ``100`` and every degradation signal present
    in ``telemetry`` subtracts a labelled penalty. The returned
    :class:`ComponentHealthResult` exposes every penalty as a
    :class:`HealthContribution` so the score is fully explainable; no penalty is
    applied for a signal that is within its limit.

    Supported ``component_type`` values (see :data:`COMPONENT_TYPES`):

    * ``"motor"`` -- current/voltage imbalance, winding temperature, vibration.
    * ``"bearing"`` -- bearing temperature, vibration.
    * ``"seal"`` -- mechanical-seal leakage.
    * ``"vfd"`` -- drive fault/trip count, harmonic distortion (THD).
    * ``"filter"`` -- normalized differential pressure (fouling/plugging).
    * ``"valve"`` -- position error, travel deviation (stiction).
    * ``"erd"`` -- energy-recovery-device transfer efficiency vs rated.
    * ``"pump"`` -- motor + bearing + seal signals plus efficiency drift.

    ``telemetry`` is a mapping of named metric -> value in the documented units
    (e.g. ``vibration_mm_s``, ``winding_temp_c``, ``seal_leakage_ml_min``,
    ``normalized_dp``, ``transfer_efficiency_pct``). Optional ``*_limit_*`` keys
    override the documented default limits. Missing signals are treated as
    nominal (no penalty).

    Args:
        component_type: One of :data:`COMPONENT_TYPES`.
        telemetry: Named metric values in documented units.

    Returns:
        A :class:`ComponentHealthResult` (score, band, contributions).

    Raises:
        ValueError: If ``component_type`` is unknown or ``telemetry`` is not a
            mapping.
    """
    if component_type not in _COMPONENT_PENALTY_FN:
        raise ValueError(
            f"component_type must be one of {COMPONENT_TYPES}; got {component_type!r}."
        )
    if not isinstance(telemetry, dict):
        raise ValueError("telemetry must be a mapping of metric name -> value.")

    contributions: list[HealthContribution] = []
    _COMPONENT_PENALTY_FN[component_type](telemetry, contributions)

    score = _clamp(100.0 + sum(c.delta for c in contributions), 0.0, 100.0)
    return ComponentHealthResult(
        component_type=component_type,
        score=round(score, 1),
        band=health_band(score),
        contributions=contributions,
    )


# ---------------------------------------------------------------------------
# Operating envelope
# ---------------------------------------------------------------------------


def operating_envelope_score(history: list[dict[str, float]]) -> OperatingEnvelopeResult:
    """Fraction of operating time spent in each envelope regime.

    Given a time-series ``history`` (one sample per record) this returns the
    fraction of samples that fall into each of five operating regimes. Running a
    rotating machine away from its best-efficiency point (BEP), at low flow,
    against high pressure, hot, or in a cavitation-prone state accelerates wear;
    these fractions quantify how much of the observed duty was spent outside the
    healthy envelope.

    Each ``history`` record may contain (all optional, documented units):

    * ``flow_m3h`` with ``bep_flow_m3h`` (and optional ``bep_tolerance`` fraction,
      default 0.10): a sample is "at BEP" when flow is within tolerance of BEP,
      "low flow" when below ``low_flow_fraction`` (default 0.70) of BEP.
    * ``pressure_bar`` with ``max_pressure_bar``: "high pressure" when pressure
      exceeds the rated maximum.
    * ``temperature_c`` with ``temp_limit_c``: "excess temperature" when above
      the limit.
    * ``cavitation_risk`` (truthy) OR ``npsh_available_m`` with
      ``npsh_required_m``: cavitation risk when available NPSH is at/below the
      required NPSH (with a documented 0.5 m margin) or the flag is set.

    Args:
        history: A list of per-sample telemetry mappings.

    Returns:
        An :class:`OperatingEnvelopeResult` with each regime's time fraction.

    Raises:
        ValueError: If ``history`` is empty or not a list of mappings.
    """
    if not isinstance(history, list) or not history:
        raise ValueError("history must be a non-empty list of telemetry mappings.")

    n = len(history)
    at_bep = low_flow = high_pressure = excess_temp = cavitation = 0

    for sample in history:
        if not isinstance(sample, dict):
            raise ValueError("each history record must be a mapping.")
        flow = sample.get("flow_m3h")
        bep = sample.get("bep_flow_m3h")
        if flow is not None and bep:
            tol = float(sample.get("bep_tolerance", 0.10))
            low_frac = float(sample.get("low_flow_fraction", 0.70))
            ratio = float(flow) / float(bep)
            if abs(ratio - 1.0) <= tol:
                at_bep += 1
            if ratio < low_frac:
                low_flow += 1

        pressure = sample.get("pressure_bar")
        max_p = sample.get("max_pressure_bar")
        if pressure is not None and max_p and float(pressure) > float(max_p):
            high_pressure += 1

        temp = sample.get("temperature_c")
        temp_limit = sample.get("temp_limit_c")
        if temp is not None and temp_limit is not None and float(temp) > float(temp_limit):
            excess_temp += 1

        cav = False
        if sample.get("cavitation_risk"):
            cav = True
        npsh_a = sample.get("npsh_available_m")
        npsh_r = sample.get("npsh_required_m")
        if npsh_a is not None and npsh_r is not None:
            if float(npsh_a) <= float(npsh_r) + 0.5:
                cav = True
        if cav:
            cavitation += 1

    return OperatingEnvelopeResult(
        samples=n,
        at_bep_fraction=round(at_bep / n, 4),
        low_flow_fraction=round(low_flow / n, 4),
        high_pressure_fraction=round(high_pressure / n, 4),
        excess_temperature_fraction=round(excess_temp / n, 4),
        cavitation_risk_fraction=round(cavitation / n, 4),
    )


# ---------------------------------------------------------------------------
# Remaining useful life (preliminary ensemble)
# ---------------------------------------------------------------------------


def _health_slope_per_day(health_trend: list[float]) -> tuple[float, float]:
    """Least-squares health slope (points/day) and the latest health value.

    ``health_trend`` is a chronological sequence of health scores sampled once
    per day (oldest first, newest last). Returns ``(slope, current)`` where a
    negative slope indicates degradation.
    """
    n = len(health_trend)
    current = float(health_trend[-1])
    if n < 2:
        return 0.0, current
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(health_trend) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0, current
    slope = sum((x - mean_x) * (health_trend[i] - mean_y) for i, x in enumerate(xs)) / denom
    return slope, current


def remaining_useful_life_days(
    health_trend: list[float],
    duty_cycle: float,
    maintenance_age_days: float,
    recommended_interval_days: float,
    comparable_asset_factor: float = 1.0,
    failure_threshold: float = DEFAULT_FAILURE_THRESHOLD,
) -> RemainingUsefulLifeResult:
    """Preliminary remaining-useful-life estimate with an uncertainty band.

    This is a **preliminary**, advisory ensemble estimate -- never a validated
    or guaranteed time-to-failure. The method:

    1. **Health-slope extrapolation.** Fit the recent ``health_trend`` (daily
       health scores, oldest first) with a least-squares line and project the
       time for health to decay from its current value to ``failure_threshold``.
       A flat/improving trend yields an open-ended (capped) life.
    2. **Duty-cycle severity.** Scale the projection by ``(1 - k * duty_cycle)``
       so a harder-run asset (``duty_cycle`` near 1) is given a shorter life.
    3. **Maintenance age vs interval.** Shorten life as the asset approaches or
       passes its ``recommended_interval_days`` since the last maintenance.
    4. **Comparable-asset behavior.** Multiply by ``comparable_asset_factor``
       (>1 = fleet peers last longer than this unit's trend implies; <1 =
       peers fail sooner).

    The three modulators are combined into a single point estimate; the
    uncertainty band widens with duty severity and with how little trend data is
    available (``+/-`` a fraction of the estimate, floored so the band is never
    degenerate).

    Args:
        health_trend: Chronological daily health scores (0-100), oldest first.
        duty_cycle: Fractional duty/severity in ``[0, 1]``.
        maintenance_age_days: Days since last maintenance (>= 0).
        recommended_interval_days: Recommended maintenance interval, days (> 0).
        comparable_asset_factor: Fleet-relative longevity multiplier (> 0).
        failure_threshold: Health value treated as end-of-life (0-100).

    Returns:
        A :class:`RemainingUsefulLifeResult` with point estimate + ``(lower,
        upper)`` band and ``provenance = "preliminary"``.

    Raises:
        ValueError: On empty trend, out-of-range duty cycle, non-positive
            interval or factor, or negative maintenance age.
    """
    if not isinstance(health_trend, list) or not health_trend:
        raise ValueError("health_trend must be a non-empty list of health scores.")
    if not 0.0 <= duty_cycle <= 1.0:
        raise ValueError("duty_cycle must be in [0, 1].")
    if maintenance_age_days < 0:
        raise ValueError("maintenance_age_days must be non-negative.")
    if recommended_interval_days <= 0:
        raise ValueError("recommended_interval_days must be positive.")
    if comparable_asset_factor <= 0:
        raise ValueError("comparable_asset_factor must be positive.")

    slope, current = _health_slope_per_day(health_trend)
    basis: list[str] = []

    #: Upper cap on the projected life (days) to keep an open-ended trend finite.
    horizon_cap = 3.0 * recommended_interval_days + 365.0

    headroom = max(0.0, current - failure_threshold)
    if slope < -1e-6:
        base_days = headroom / (-slope)
        basis.append(
            f"health slope {slope:.2f}/day projects {base_days:.0f} d to "
            f"threshold {failure_threshold:.0f}"
        )
    else:
        base_days = horizon_cap
        basis.append("health trend flat/improving; life capped at screening horizon")

    duty_factor = _clamp(1.0 - 0.6 * duty_cycle, 0.25, 1.0)
    basis.append(f"duty-cycle severity {duty_cycle:.2f} -> x{duty_factor:.2f}")

    interval_ratio = maintenance_age_days / recommended_interval_days
    maint_factor = _clamp(1.0 - 0.5 * interval_ratio, 0.2, 1.0)
    basis.append(
        f"maintenance age {maintenance_age_days:.0f}/{recommended_interval_days:.0f} d "
        f"-> x{maint_factor:.2f}"
    )
    basis.append(f"comparable-asset factor x{comparable_asset_factor:.2f}")

    rul = base_days * duty_factor * maint_factor * comparable_asset_factor
    rul = min(rul, horizon_cap)

    # Uncertainty widens with duty severity and with a short trend history.
    trend_penalty = 0.15 if len(health_trend) >= 5 else 0.30
    spread = _clamp(0.25 + 0.5 * duty_cycle + trend_penalty, 0.2, 0.9)
    lower = max(0.0, rul * (1.0 - spread))
    upper = rul * (1.0 + spread)

    return RemainingUsefulLifeResult(
        rul_days=round(rul, 1),
        lower_days=round(lower, 1),
        upper_days=round(upper, 1),
        method="health-slope extrapolation modulated by duty/maintenance/fleet",
        basis=basis,
    )


# ---------------------------------------------------------------------------
# Failure probability (monotonic hazard)
# ---------------------------------------------------------------------------


def failure_probability(
    health_band_label: str,
    anomaly_score: float,
    rul_days: float,
) -> FailureProbabilityResult:
    """Monotonic failure-probability hazard mapped onto fixed horizons.

    Combines three risk signals into a single hazard rate and integrates a
    memoryless (exponential) survival model over the ``{24h, 7d, 30d, 90d}``
    horizons, returning ``P(fail before horizon)`` for each. The mapping is
    **monotonic** in every input: a worse health band, a higher anomaly score,
    or a shorter remaining-useful-life all (weakly) increase the probability at
    every horizon.

    Hazard construction (per day):

    * ``base`` from the health band (Healthy -> Critical: rising base hazard).
    * ``+`` an anomaly term proportional to ``anomaly_score`` in ``[0, 1]``.
    * ``+`` an RUL term ``~ 1 / rul_days`` so a short RUL dominates the hazard.

    ``P(t) = 1 - exp(-hazard * t_days)``.

    This is a **preliminary** advisory estimate, not a validated or guaranteed
    probability of failure.

    Args:
        health_band_label: One of ``Healthy``/``Monitor``/``Degraded``/
            ``HighRisk``/``Critical``.
        anomaly_score: Composite anomaly score in ``[0, 1]``.
        rul_days: Preliminary remaining-useful-life in days (>= 0).

    Returns:
        A :class:`FailureProbabilityResult` with a probability per horizon and
        ``provenance = "preliminary"``.

    Raises:
        ValueError: If the band is unknown, anomaly is outside ``[0, 1]``, or
            ``rul_days`` is negative.
    """
    if health_band_label not in _BAND_HAZARD_BASE:
        raise ValueError(
            f"health_band_label must be one of {sorted(_BAND_HAZARD_BASE)}; "
            f"got {health_band_label!r}."
        )
    if not 0.0 <= anomaly_score <= 1.0:
        raise ValueError("anomaly_score must be in [0, 1].")
    if rul_days < 0:
        raise ValueError("rul_days must be non-negative.")

    base = _BAND_HAZARD_BASE[health_band_label]
    anomaly_term = 0.25 * anomaly_score
    # Short RUL -> high hazard; +1 day guards against division by zero.
    rul_term = 30.0 / (rul_days + 1.0) * 0.05
    hazard = base + anomaly_term + rul_term

    horizons = {
        label: round(1.0 - math.exp(-hazard * days), 4)
        for label, days in FAILURE_HORIZON_DAYS.items()
    }
    return FailureProbabilityResult(horizons=horizons)


# ---------------------------------------------------------------------------
# Maintenance prioritization
# ---------------------------------------------------------------------------


def maintenance_priority(
    failure_prob: float,
    consequence: float,
    production_impact: float,
    redundancy: float,
    spares_available: bool,
    safety_or_wq_weight: float = 1.0,
) -> MaintenancePriorityResult:
    """Rank score for maintenance prioritization (higher = more urgent).

    Blends the likelihood of failure with the consequence of that failure to
    produce a single comparable rank score. The score rises with failure
    probability, consequence severity, production impact and any
    safety/water-quality weighting, and falls when installed redundancy or
    on-hand spares reduce the operational exposure.

    Formula::

        exposure   = failure_prob * (consequence + production_impact)
                     * safety_or_wq_weight
        redundancy_factor = 1 / (1 + redundancy)      # standbys cut urgency
        spares_factor     = 0.85 if spares_available else 1.15
        rank_score = 100 * exposure * redundancy_factor * spares_factor

    Args:
        failure_prob: Probability of failure in the decision window ``[0, 1]``
            (e.g. the 30-day horizon from :func:`failure_probability`).
        consequence: Consequence severity of a failure in ``[0, 1]``.
        production_impact: Fractional production/throughput at risk ``[0, 1]``.
        redundancy: Number of equivalent standby units available (>= 0).
        spares_available: Whether the required spares are on hand.
        safety_or_wq_weight: Multiplier (>= 1 typical) elevating assets whose
            failure carries a safety or water-quality consequence.

    Returns:
        A :class:`MaintenancePriorityResult` with the rank score and the factor
        breakdown used to compute it.

    Raises:
        ValueError: If any of the ``[0, 1]`` inputs is out of range, redundancy
            is negative, or the weight is non-positive.
    """
    if not 0.0 <= failure_prob <= 1.0:
        raise ValueError("failure_prob must be in [0, 1].")
    if not 0.0 <= consequence <= 1.0:
        raise ValueError("consequence must be in [0, 1].")
    if not 0.0 <= production_impact <= 1.0:
        raise ValueError("production_impact must be in [0, 1].")
    if redundancy < 0:
        raise ValueError("redundancy must be non-negative.")
    if safety_or_wq_weight <= 0:
        raise ValueError("safety_or_wq_weight must be positive.")

    exposure = failure_prob * (consequence + production_impact) * safety_or_wq_weight
    redundancy_factor = 1.0 / (1.0 + redundancy)
    spares_factor = 0.85 if spares_available else 1.15
    rank_score = 100.0 * exposure * redundancy_factor * spares_factor

    return MaintenancePriorityResult(
        rank_score=round(rank_score, 2),
        factors={
            "failure_prob": round(failure_prob, 4),
            "consequence": round(consequence, 4),
            "production_impact": round(production_impact, 4),
            "redundancy_factor": round(redundancy_factor, 4),
            "spares_factor": spares_factor,
            "safety_or_wq_weight": round(safety_or_wq_weight, 4),
        },
    )
