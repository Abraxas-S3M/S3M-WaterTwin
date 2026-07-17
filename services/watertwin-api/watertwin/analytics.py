"""Transparent health scoring, physics-informed anomaly detection, and
cyber-physical consistency checks for water pumping assets.

Phase 3 of the S3M-WaterTwin analytics stack.

Design goals
------------
* **Transparency** — every point deducted from a pump's health score is recorded
  as a :class:`HealthContribution` so the breakdown is always inspectable.
* **Physics-informed** — the anomaly score blends statistical deviation with
  first-principles hydraulic/pump-curve residuals and cross-sensor consistency.
* **Cyber-physical safety** — impossible physical states (e.g. a pump reported as
  running while flow is zero) are flagged explicitly.

Phase 2 (the canonical asset/telemetry domain model) is not yet available in this
tree, so lightweight, well-documented dataclasses are provided here. They are
intentionally permissive (sensible defaults, optional fields) so telemetry with
missing channels degrades gracefully instead of raising.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "ANOMALY_WEIGHTS",
    "AnomalyDomain",
    "AnomalyResult",
    "Baseline",
    "HealthBand",
    "HealthContribution",
    "HealthScore",
    "PumpAsset",
    "Telemetry",
    "anomaly_score",
    "cyber_physical_flags",
    "pump_health_score",
]

# Physical constants.
_RHO_WATER = 1000.0  # kg/m^3
_GRAVITY = 9.80665  # m/s^2

# Cyber-physical thresholds (telemetry-only, so absolute values are used).
_FLOW_ZERO = 1.0  # m^3/h — flow at or below this is treated as "no flow"
_POWER_HIGH = 1.0  # kW — motor power above this is meaningfully "on"
_POWER_ZERO = 0.1  # kW — motor power at or below this is "no power"
_LEVEL_RATE_ZERO = 1e-3  # m/s — level rate below this is "no change"


# ---------------------------------------------------------------------------
# Domain model (placeholder until Phase 2 lands)
# ---------------------------------------------------------------------------
@dataclass
class PumpAsset:
    """Nameplate / design characteristics of a pump asset.

    Values are the design references against which live telemetry is compared.
    """

    asset_id: str = "pump"
    # Alarm / design limits.
    vibration_limit: float = 7.1  # mm/s RMS (ISO 10816 zone C/D boundary)
    bearing_temp_limit: float = 90.0  # deg C
    seal_leakage_limit: float = 5.0  # ml/min
    cavitation_index_limit: float = 0.30  # dimensionless (higher = worse)
    # Best-efficiency-point (BEP) references.
    rated_flow: float = 100.0  # m^3/h at BEP
    rated_head: float = 50.0  # m at BEP
    rated_power: float = 15.0  # kW electrical at BEP
    rated_efficiency: float = 0.85  # fraction (0..1) at BEP
    rated_current: float = 28.0  # A per phase, nominal
    # Maintenance policy.
    maintenance_interval_days: float = 365.0
    # Consequence weighting for operational criticality (0..1).
    criticality: float = 0.5


@dataclass
class Telemetry:
    """A single telemetry snapshot for a pump asset.

    All channels are optional; missing values simply mean the corresponding
    checks are skipped rather than raising.
    """

    status: str = "running"  # running | stopped | idle | ...
    flow: float = 0.0  # m^3/h
    vibration: float = 0.0  # mm/s RMS
    bearing_temperature: float = 25.0  # deg C
    efficiency: float | None = None  # fraction 0..1
    motor_power: float = 0.0  # kW electrical
    motor_current: Sequence[float] | None = None  # per-phase amps
    seal_leakage: float = 0.0  # ml/min
    cavitation_index: float = 0.0  # dimensionless
    suction_pressure: float | None = None  # kPa absolute
    discharge_pressure: float | None = None  # kPa absolute
    head: float | None = None  # m (measured; derived from pressures if absent)
    water_temperature: float = 20.0  # deg C
    level: float | None = None  # m
    level_rate: float = 0.0  # m/s (positive = rising)
    sensor_uncertainty: float = 0.0  # 0..1 aggregate measurement uncertainty
    days_since_maintenance: float = 0.0

    @property
    def is_running(self) -> bool:
        return self.status.strip().lower() == "running"


@dataclass
class Baseline:
    """Learned normal-operating baseline used by :func:`anomaly_score`.

    ``metrics`` maps a signal name to a ``(mean, std)`` tuple. ``failure_patterns``
    is an optional list of known failure signatures, each a mapping of signal name
    to a normalized (0..1) activation.
    """

    metrics: dict[str, tuple[float, float]] = field(default_factory=dict)
    failure_patterns: list[dict[str, float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Health scoring
# ---------------------------------------------------------------------------
class HealthBand(str, Enum):
    """Qualitative health band derived from a numeric 0..100 score."""

    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"

    @classmethod
    def from_score(cls, score: float) -> HealthBand:
        if score >= 90:
            return cls.EXCELLENT
        if score >= 75:
            return cls.GOOD
        if score >= 50:
            return cls.FAIR
        if score >= 25:
            return cls.POOR
        return cls.CRITICAL


@dataclass(frozen=True)
class HealthContribution:
    """A single, human-readable line item in the health-score breakdown.

    ``delta`` is the (negative) number of points subtracted from the score.
    """

    factor: str
    delta: float
    detail: str


@dataclass
class HealthScore:
    """Result of :func:`pump_health_score`.

    ``contributions`` is never hidden — it always lists every penalty applied so
    the score is fully explainable.
    """

    score: float
    band: HealthBand
    contributions: list[HealthContribution] = field(default_factory=list)


# Nominal penalty weights (points). These sum to 100 so a fully-failed pump can
# reach a score of 0.
_HEALTH_WEIGHTS = {
    "vibration": 18.0,
    "bearing_temperature": 15.0,
    "bep_efficiency": 15.0,
    "current_imbalance": 12.0,
    "cavitation": 12.0,
    "seal_leakage": 10.0,
    "maintenance_age": 10.0,
    "sensor_uncertainty": 8.0,
}


def _ratio_penalty(value: float | None, limit: float | None, weight: float,
                   *, warn_frac: float = 0.8, cap: float = 1.5) -> float:
    """Return a (negative) penalty that grows once ``value`` exceeds ``warn_frac``
    of ``limit`` and reaches ``-weight`` at the limit itself.
    """
    if value is None or limit is None or limit <= 0:
        return 0.0
    ratio = value / limit
    if ratio <= warn_frac:
        return 0.0
    frac = (ratio - warn_frac) / (1.0 - warn_frac)
    return -weight * min(frac, cap)


def _current_imbalance_pct(currents: Sequence[float] | None) -> float | None:
    vals = [c for c in currents if c is not None] if currents else []
    if len(vals) < 2:
        return None
    avg = sum(vals) / len(vals)
    if avg <= 0:
        return None
    return (max(vals) - min(vals)) / avg * 100.0


def pump_health_score(asset: PumpAsset, telemetry: Telemetry) -> HealthScore:
    """Compute a transparent 0..100 health score for a pump.

    The score starts at 100 and subtracts weighted penalties, each recorded as a
    :class:`HealthContribution` so the breakdown is fully visible.
    """
    contributions: list[HealthContribution] = []

    def add(factor: str, delta: float, detail: str) -> None:
        if delta < 0:
            contributions.append(HealthContribution(factor, round(delta, 3), detail))

    # 1. Vibration vs limit.
    p = _ratio_penalty(telemetry.vibration, asset.vibration_limit,
                       _HEALTH_WEIGHTS["vibration"])
    add("vibration", p,
        f"vibration {telemetry.vibration:.2f} mm/s vs limit {asset.vibration_limit:.2f}")

    # 2. Bearing temperature vs limit.
    p = _ratio_penalty(telemetry.bearing_temperature, asset.bearing_temp_limit,
                       _HEALTH_WEIGHTS["bearing_temperature"])
    add("bearing_temperature", p,
        f"bearing temp {telemetry.bearing_temperature:.1f}C vs "
        f"limit {asset.bearing_temp_limit:.1f}C")

    # 3. BEP / efficiency shortfall.
    p_eff = 0.0
    detail_parts: list[str] = []
    if telemetry.efficiency is not None and asset.rated_efficiency > 0:
        shortfall = (asset.rated_efficiency - telemetry.efficiency) / asset.rated_efficiency
        if shortfall > 0.05:
            p_eff -= _HEALTH_WEIGHTS["bep_efficiency"] * min(1.5, (shortfall - 0.05) / 0.25)
            detail_parts.append(
                f"efficiency {telemetry.efficiency:.2f} vs rated {asset.rated_efficiency:.2f}"
            )
    if telemetry.is_running and asset.rated_flow > 0 and telemetry.flow > 0:
        flow_dev = abs(telemetry.flow - asset.rated_flow) / asset.rated_flow
        if flow_dev > 0.25:
            p_eff -= 6.0 * min(1.0, (flow_dev - 0.25) / 0.5)
            detail_parts.append(
                f"flow {telemetry.flow:.1f} off BEP {asset.rated_flow:.1f} m3/h"
            )
    add("bep_efficiency", p_eff, "; ".join(detail_parts) or "BEP/efficiency shortfall")

    # 4. Motor current imbalance.
    imbalance = _current_imbalance_pct(telemetry.motor_current)
    if imbalance is not None and imbalance > 2.0:
        p = -_HEALTH_WEIGHTS["current_imbalance"] * min(1.5, (imbalance - 2.0) / 8.0)
        add("current_imbalance", p, f"phase current imbalance {imbalance:.1f}%")

    # 5. Cavitation index.
    p = _ratio_penalty(telemetry.cavitation_index, asset.cavitation_index_limit,
                       _HEALTH_WEIGHTS["cavitation"], warn_frac=0.5)
    add("cavitation", p,
        f"cavitation index {telemetry.cavitation_index:.3f} vs "
        f"limit {asset.cavitation_index_limit:.3f}")

    # 6. Seal leakage.
    p = _ratio_penalty(telemetry.seal_leakage, asset.seal_leakage_limit,
                       _HEALTH_WEIGHTS["seal_leakage"], warn_frac=0.5)
    add("seal_leakage", p,
        f"seal leakage {telemetry.seal_leakage:.2f} vs limit {asset.seal_leakage_limit:.2f}")

    # 7. Maintenance age.
    p = _ratio_penalty(telemetry.days_since_maintenance, asset.maintenance_interval_days,
                       _HEALTH_WEIGHTS["maintenance_age"], warn_frac=0.8, cap=2.0)
    add("maintenance_age", p,
        f"{telemetry.days_since_maintenance:.0f} days since maintenance vs "
        f"interval {asset.maintenance_interval_days:.0f}")

    # 8. Sensor uncertainty.
    if telemetry.sensor_uncertainty > 0.1:
        p = -_HEALTH_WEIGHTS["sensor_uncertainty"] * min(
            1.0, (telemetry.sensor_uncertainty - 0.1) / 0.4
        )
        add("sensor_uncertainty", p,
            f"sensor uncertainty {telemetry.sensor_uncertainty:.2f}")

    raw = 100.0 + sum(c.delta for c in contributions)
    score = max(0.0, min(100.0, raw))
    return HealthScore(
        score=round(score, 2),
        band=HealthBand.from_score(score),
        contributions=contributions,
    )


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------
class AnomalyDomain(str, Enum):
    """The functional domain an anomaly most likely originates from."""

    HYDRAULIC = "hydraulic"
    MECHANICAL = "mechanical"
    SENSOR = "sensor"
    CYBER_PHYSICAL = "cyber_physical"
    STATISTICAL = "statistical"
    OPERATIONAL = "operational"


# Physics-informed blend weights. These MUST sum to 1.0 and are named so the
# blend is auditable. Do not change this weight set.
ANOMALY_WEIGHTS: dict[str, float] = {
    "statistical_deviation": 0.25,
    "hydraulic_residual": 0.25,
    "pump_curve_deviation": 0.20,
    "cross_sensor_inconsistency": 0.15,
    "failure_pattern_similarity": 0.10,
    "operational_criticality": 0.05,
}

# Which domain(s) each factor feeds when ranking the likely source.
_FACTOR_DOMAINS: dict[str, tuple[AnomalyDomain, ...]] = {
    "statistical_deviation": (AnomalyDomain.STATISTICAL,),
    "hydraulic_residual": (AnomalyDomain.HYDRAULIC,),
    "pump_curve_deviation": (AnomalyDomain.MECHANICAL,),
    "cross_sensor_inconsistency": (AnomalyDomain.SENSOR, AnomalyDomain.CYBER_PHYSICAL),
    "failure_pattern_similarity": (AnomalyDomain.MECHANICAL,),
    "operational_criticality": (AnomalyDomain.OPERATIONAL,),
}


@dataclass
class AnomalyResult:
    """Result of :func:`anomaly_score`.

    * ``score`` — final blended anomaly score in ``[0, 1]``.
    * ``factors`` — each named factor's value in ``[0, 1]``.
    * ``domains`` — :class:`AnomalyDomain` values ranked by dominant contribution.
    """

    score: float
    factors: dict[str, float]
    domains: list[AnomalyDomain] = field(default_factory=list)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _effective_head(asset: PumpAsset, telemetry: Telemetry) -> float | None:
    """Return measured head (m), deriving it from suction/discharge pressure if
    an explicit head channel is not present.
    """
    if telemetry.head is not None:
        return telemetry.head
    if telemetry.suction_pressure is not None and telemetry.discharge_pressure is not None:
        dp_kpa = telemetry.discharge_pressure - telemetry.suction_pressure
        return dp_kpa * 1000.0 / (_RHO_WATER * _GRAVITY)
    return None


def _statistical_deviation(telemetry: Telemetry, baseline: Baseline) -> float:
    signal_values = {
        "flow": telemetry.flow,
        "vibration": telemetry.vibration,
        "bearing_temperature": telemetry.bearing_temperature,
        "motor_power": telemetry.motor_power,
        "efficiency": telemetry.efficiency,
        "suction_pressure": telemetry.suction_pressure,
    }
    severities: list[float] = []
    for name, (mean, std) in baseline.metrics.items():
        value = signal_values.get(name)
        if value is None or std <= 0:
            continue
        z = abs(value - mean) / std
        severities.append(_clamp01(z / 4.0))  # 4-sigma -> saturated
    if not severities:
        return 0.0
    # Blend average behaviour with the single worst signal.
    return _clamp01(0.5 * (sum(severities) / len(severities)) + 0.5 * max(severities))


def _hydraulic_residual(asset: PumpAsset, telemetry: Telemetry) -> float:
    """Residual between measured electrical power and the power implied by the
    measured flow/head via the hydraulic power balance.
    """
    if not telemetry.is_running:
        return 0.0
    head = _effective_head(asset, telemetry)
    if head is None or telemetry.flow <= 0:
        return 0.0
    q_m3s = telemetry.flow / 3600.0
    water_power_kw = _RHO_WATER * _GRAVITY * q_m3s * head / 1000.0
    eff = telemetry.efficiency if telemetry.efficiency and telemetry.efficiency > 0 \
        else asset.rated_efficiency
    expected_power = water_power_kw / max(eff, 0.3)
    denom = max(telemetry.motor_power, expected_power, asset.rated_power, 1.0)
    residual = abs(telemetry.motor_power - expected_power) / denom
    return _clamp01(residual)


def _pump_curve_deviation(asset: PumpAsset, telemetry: Telemetry) -> float:
    """Deviation of the operating point from the design pump curve.

    A simple quadratic curve is assumed: ``H(Q) = H0 * (1 - (Q/Qmax)^2)`` with
    shutoff head ``H0 ~ 1.25 * rated_head`` and max flow ``Qmax ~ 1.4 * rated_flow``.
    """
    if not telemetry.is_running or asset.rated_flow <= 0 or asset.rated_head <= 0:
        return 0.0
    head = _effective_head(asset, telemetry)
    if head is None or telemetry.flow <= 0:
        return 0.0
    h0 = 1.25 * asset.rated_head
    q_max = 1.4 * asset.rated_flow
    expected = h0 * (1.0 - (telemetry.flow / q_max) ** 2)
    expected = max(expected, 0.05 * asset.rated_head)
    deviation = abs(head - expected) / expected
    return _clamp01(deviation / 0.30)  # 30% off-curve -> saturated


def _cross_sensor_inconsistency(asset: PumpAsset, telemetry: Telemetry) -> float:
    """Consistency between physically-coupled sensors, including impossible
    cyber-physical states and a current/power cross-check.
    """
    score = 0.3 * len(cyber_physical_flags(telemetry))

    # Current vs power cross-check: electrical power scales with average current.
    imbalance = _current_imbalance_pct(telemetry.motor_current)
    if imbalance is not None and imbalance > 10.0:
        score += min(0.3, (imbalance - 10.0) / 40.0)

    currents = [c for c in (telemetry.motor_current or []) if c is not None]
    if currents and asset.rated_current > 0 and asset.rated_power > 0:
        avg_current = sum(currents) / len(currents)
        current_load = avg_current / asset.rated_current
        power_load = telemetry.motor_power / asset.rated_power
        if current_load > 0.1 or power_load > 0.1:
            mismatch = abs(current_load - power_load) / max(current_load, power_load, 0.1)
            score += min(0.4, mismatch)

    return _clamp01(score)


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _failure_pattern_similarity(asset: PumpAsset, telemetry: Telemetry,
                                baseline: Baseline) -> float:
    """Similarity of the current feature vector to known failure signatures.

    If the baseline supplies explicit ``failure_patterns`` they are used;
    otherwise a set of classic built-in signatures (bearing, cavitation, seal)
    is evaluated.
    """
    vib = _clamp01(telemetry.vibration / asset.vibration_limit) if asset.vibration_limit else 0.0
    temp = _clamp01(
        (telemetry.bearing_temperature - 40.0) / max(asset.bearing_temp_limit - 40.0, 1.0)
    )
    cav = _clamp01(telemetry.cavitation_index / asset.cavitation_index_limit) \
        if asset.cavitation_index_limit else 0.0
    seal = _clamp01(telemetry.seal_leakage / asset.seal_leakage_limit) \
        if asset.seal_leakage_limit else 0.0
    eff_short = 0.0
    if telemetry.efficiency is not None and asset.rated_efficiency > 0:
        eff_short = _clamp01(
            (asset.rated_efficiency - telemetry.efficiency) / asset.rated_efficiency
        )

    feature = {
        "vibration": vib,
        "bearing_temperature": temp,
        "cavitation": cav,
        "seal_leakage": seal,
        "efficiency_shortfall": eff_short,
    }

    if baseline.failure_patterns:
        return _clamp01(max(_cosine_similarity(feature, p) for p in baseline.failure_patterns))

    signatures = [
        min(vib, temp),  # bearing failure: high vibration + high temperature
        min(cav, eff_short),  # cavitation: high cavitation + efficiency loss
        seal,  # seal failure: leakage
    ]
    return _clamp01(max(signatures))


def _operational_criticality(asset: PumpAsset, telemetry: Telemetry) -> float:
    criticality = _clamp01(asset.criticality)
    running_factor = 1.0 if telemetry.is_running else 0.3
    return _clamp01(criticality * running_factor)


def anomaly_score(asset: PumpAsset, telemetry: Telemetry, baseline: Baseline) -> AnomalyResult:
    """Compute a physics-informed anomaly score in ``[0, 1]``.

    The score is a weighted blend of named factors (see :data:`ANOMALY_WEIGHTS`),
    each itself bounded to ``[0, 1]``. Contributing :class:`AnomalyDomain` values
    are ranked by their weighted contribution to the final score.
    """
    factors: dict[str, float] = {
        "statistical_deviation": _statistical_deviation(telemetry, baseline),
        "hydraulic_residual": _hydraulic_residual(asset, telemetry),
        "pump_curve_deviation": _pump_curve_deviation(asset, telemetry),
        "cross_sensor_inconsistency": _cross_sensor_inconsistency(asset, telemetry),
        "failure_pattern_similarity": _failure_pattern_similarity(asset, telemetry, baseline),
        "operational_criticality": _operational_criticality(asset, telemetry),
    }
    factors = {name: _clamp01(value) for name, value in factors.items()}

    score = sum(ANOMALY_WEIGHTS[name] * value for name, value in factors.items())
    score = _clamp01(score)

    # Rank domains by the summed weighted contribution of their feeding factors.
    domain_scores: dict[AnomalyDomain, float] = {}
    for name, value in factors.items():
        contribution = ANOMALY_WEIGHTS[name] * value
        if contribution <= 0:
            continue
        for domain in _FACTOR_DOMAINS[name]:
            domain_scores[domain] = domain_scores.get(domain, 0.0) + contribution
    domains = [d for d, _ in sorted(domain_scores.items(), key=lambda kv: kv[1], reverse=True)]

    return AnomalyResult(score=round(score, 4), factors=factors, domains=domains)


# ---------------------------------------------------------------------------
# Cyber-physical consistency
# ---------------------------------------------------------------------------
def _water_vapor_pressure_kpa(temp_c: float) -> float:
    """Saturation vapor pressure of water (kPa) via the Tetens equation."""
    return 0.61078 * math.exp(17.27 * temp_c / (temp_c + 237.3))


def cyber_physical_flags(telemetry: Telemetry) -> list[str]:
    """Return the names of triggered impossible/inconsistent physical states.

    Checks:
      * ``running_no_flow`` — reported running but flow is ~0.
      * ``power_without_flow`` — motor drawing significant power but flow is ~0.
      * ``suction_below_vapor`` — suction pressure below water's vapor pressure
        at the measured temperature (physically implies flashing/cavitation).
      * ``flow_without_power`` — measurable flow while the motor draws ~no power.
      * ``level_change_without_flow`` — tank level changing while flow is ~0.
    """
    flags: list[str] = []
    flow_zero = abs(telemetry.flow) <= _FLOW_ZERO

    if telemetry.is_running and flow_zero:
        flags.append("running_no_flow")

    if telemetry.motor_power > _POWER_HIGH and flow_zero:
        flags.append("power_without_flow")

    if telemetry.suction_pressure is not None:
        p_vapor = _water_vapor_pressure_kpa(telemetry.water_temperature)
        if telemetry.suction_pressure < p_vapor:
            flags.append("suction_below_vapor")

    if abs(telemetry.flow) > _FLOW_ZERO and telemetry.motor_power <= _POWER_ZERO:
        flags.append("flow_without_power")

    if abs(telemetry.level_rate) > _LEVEL_RATE_ZERO and flow_zero:
        flags.append("level_change_without_flow")

    return flags
