"""Resilience & standby-generator physics (advisory, preliminary).

Deterministic, screening-grade calculations for grid-outage resilience of a
single RO train: a resilience-criticality rank score, a preliminary standby-
generator start probability, fuel endurance, a load-shed ordering that keeps the
high-pressure pump and essential loads last, and a service-continuity duration
under grid loss.

Everything here is **advisory and preliminary** -- screening estimates, never
validated availability or guaranteed run-time. Functions are pure and validate
their inputs; the API layer maps them onto the canonical resilience models. No
function here writes to any control system.
"""

from __future__ import annotations

#: Priority weight used to order load shedding. Lower weight is shed first, so
#: the high-pressure pump / critical loads (highest weight) are shed last.
_PRIORITY_WEIGHT: dict[str, int] = {
    "non_essential": 0,
    "essential": 1,
    "critical": 2,
}

#: Preliminary provenance tag for resilience outputs.
PRELIMINARY = "preliminary"


def resilience_criticality_score(
    customer_or_production_impact: float,
    failure_probability: float,
    recovery_time_hours: float,
    dependency_centrality: float,
    backup_deficiency: float,
    recovery_time_reference_hours: float = 48.0,
) -> float:
    """Preliminary resilience-criticality rank score in [0, 100].

    A higher score means the asset is more critical to sustain under a grid loss.
    It is a transparent weighted blend of five drivers (each contributing more as
    it rises): customer/production impact, failure probability, normalised
    recovery time, dependency centrality and backup deficiency.

    Args:
        customer_or_production_impact: Impact if lost, fraction in [0, 1].
        failure_probability: Probability of loss under the scenario, [0, 1].
        recovery_time_hours: Time to restore the asset, hours (>= 0).
        dependency_centrality: How many downstream loads depend on it, [0, 1].
        backup_deficiency: Lack of backup/redundancy, [0, 1] (1 = no backup).
        recovery_time_reference_hours: Normalisation horizon for recovery time.

    Returns:
        Rank score in [0, 100].

    Raises:
        ValueError: If any fraction is outside [0, 1] or a time is negative.
    """
    _require_unit(
        customer_or_production_impact=customer_or_production_impact,
        failure_probability=failure_probability,
        dependency_centrality=dependency_centrality,
        backup_deficiency=backup_deficiency,
    )
    if recovery_time_hours < 0:
        raise ValueError("recovery_time_hours must be non-negative.")
    if recovery_time_reference_hours <= 0:
        raise ValueError("recovery_time_reference_hours must be positive.")

    norm_recovery = min(1.0, recovery_time_hours / recovery_time_reference_hours)
    # Weights sum to 1.0; impact and failure probability dominate.
    score = (
        0.30 * customer_or_production_impact
        + 0.25 * failure_probability
        + 0.15 * norm_recovery
        + 0.15 * dependency_centrality
        + 0.15 * backup_deficiency
    )
    return round(100.0 * score, 3)


def generator_start_probability(
    battery: float,
    last_test_days: float,
    maintenance_due: bool,
    base_reliability: float = 0.98,
) -> float:
    """Preliminary standby-generator start probability in [0, 1].

    Screening estimate of the chance the standby generator starts on demand,
    de-rated from a nominal ``base_reliability`` by low starter-battery charge,
    a long interval since the last test-run, and an overdue maintenance flag.
    This is a **preliminary** reliability indicator, not a guaranteed
    availability figure.

    Args:
        battery: Starter-battery state of charge, fraction in [0, 1].
        last_test_days: Days since the last successful test-run (>= 0).
        maintenance_due: Whether scheduled maintenance is overdue.
        base_reliability: Nominal start reliability of a healthy set, [0, 1].

    Returns:
        Start probability in [0, 1].

    Raises:
        ValueError: If ``battery``/``base_reliability`` are outside [0, 1] or
            ``last_test_days`` is negative.
    """
    _require_unit(battery=battery, base_reliability=base_reliability)
    if last_test_days < 0:
        raise ValueError("last_test_days must be non-negative.")

    # Battery below ~40% charge sharply reduces cranking reliability.
    battery_factor = max(0.0, min(1.0, battery / 0.4))
    # Confidence decays as the set goes untested (30-day cadence reference).
    test_factor = max(0.5, 1.0 - 0.01 * max(0.0, last_test_days - 30.0))
    maintenance_factor = 0.85 if maintenance_due else 1.0

    prob = base_reliability * battery_factor * test_factor * maintenance_factor
    return round(max(0.0, min(1.0, prob)), 4)


def fuel_endurance_hours(
    fuel_level_litres: float,
    consumption_rate_l_per_h: float,
    load_fraction: float,
    idle_consumption_fraction: float = 0.25,
) -> float:
    """Preliminary generator fuel endurance in hours.

    Effective fuel burn rises with load: a diesel genset burns roughly
    ``idle_consumption_fraction`` of its full-load rate at no load and the full
    rate at full load. Endurance is remaining fuel divided by that effective
    burn, so it **decreases monotonically as load increases**.

    Args:
        fuel_level_litres: Usable fuel remaining, litres (>= 0).
        consumption_rate_l_per_h: Full-load fuel consumption, L/h (> 0).
        load_fraction: Electrical load as a fraction of rating, [0, 1].
        idle_consumption_fraction: No-load burn as a fraction of full load,
            in (0, 1].

    Returns:
        Endurance in hours (>= 0).

    Raises:
        ValueError: If inputs are out of range.
    """
    if fuel_level_litres < 0:
        raise ValueError("fuel_level_litres must be non-negative.")
    if consumption_rate_l_per_h <= 0:
        raise ValueError("consumption_rate_l_per_h must be positive.")
    _require_unit(load_fraction=load_fraction)
    if not 0.0 < idle_consumption_fraction <= 1.0:
        raise ValueError("idle_consumption_fraction must be in (0, 1].")

    effective = consumption_rate_l_per_h * (
        idle_consumption_fraction + (1.0 - idle_consumption_fraction) * load_fraction
    )
    return round(fuel_level_litres / effective, 3)


def load_shed_priority(assets: list[dict]) -> list[dict]:
    """Order loads for shedding to sustain critical loads under limited generation.

    Loads are shed lowest-priority first, so critical loads -- notably the
    high-pressure pump -- are shed last. Within a priority band, larger
    non-essential loads are shed first (they free the most generation soonest).

    Args:
        assets: Each item is a mapping with ``asset_id``, ``load_kw`` and a
            ``priority`` of ``"critical"``/``"essential"``/``"non_essential"``.
            An optional ``asset_type`` of ``"hp_pump"`` is always treated as the
            single most-critical load.

    Returns:
        A new list ordered first-to-shed → last-to-shed, each item annotated with
        a 1-based ``shed_order`` (1 = shed first).

    Raises:
        ValueError: If an asset is missing ``load_kw`` or has an unknown priority.
    """
    ordered: list[dict] = []
    for asset in assets:
        priority = str(asset.get("priority", "non_essential"))
        if priority not in _PRIORITY_WEIGHT:
            raise ValueError(f"unknown priority: {priority}")
        if asset.get("load_kw") is None:
            raise ValueError(f"asset {asset.get('asset_id')} is missing load_kw")
        weight = _PRIORITY_WEIGHT[priority]
        # The HP pump is the single load kept online the longest.
        if asset.get("asset_type") == "hp_pump":
            weight = max(_PRIORITY_WEIGHT.values()) + 1
        ordered.append({**asset, "_weight": weight})

    # Shed first = lowest weight; break ties by shedding the largest load first.
    ordered.sort(key=lambda a: (a["_weight"], -float(a["load_kw"])))
    result: list[dict] = []
    for i, asset in enumerate(ordered, start=1):
        item = {k: v for k, v in asset.items() if k != "_weight"}
        item["shed_order"] = i
        result.append(item)
    return result


def service_continuity_hours(scenario: dict) -> float:
    """Preliminary service-continuity duration under a grid-loss scenario, hours.

    How long the train can hold product-water service under grid loss. The UPS/
    battery bridges the transfer to generator power; if the generator is
    available and critical loads are sustained, endurance is the fuel endurance
    plus the battery bridge, otherwise it is limited to the battery bridge alone.

    Args:
        scenario: Mapping with ``generator_available`` (bool),
            ``fuel_endurance_hours`` (>= 0), ``battery_bridge_minutes`` (>= 0),
            and ``critical_loads_sustained`` (bool).

    Returns:
        Service-continuity duration in hours (>= 0).

    Raises:
        ValueError: If a duration is negative.
    """
    generator_available = bool(scenario.get("generator_available", False))
    fuel_hours = float(scenario.get("fuel_endurance_hours", 0.0))
    battery_minutes = float(scenario.get("battery_bridge_minutes", 0.0))
    critical_sustained = bool(scenario.get("critical_loads_sustained", True))
    if fuel_hours < 0 or battery_minutes < 0:
        raise ValueError("durations must be non-negative.")

    battery_hours = battery_minutes / 60.0
    if generator_available and critical_sustained:
        hours = battery_hours + fuel_hours
    elif generator_available and not critical_sustained:
        # Generator runs but cannot carry the critical load: bridge only.
        hours = battery_hours
    else:
        # No generation: service holds only for the battery bridge.
        hours = battery_hours
    return round(hours, 3)


def _require_unit(**named_values: float) -> None:
    """Raise ``ValueError`` if any provided value is outside [0, 1]."""
    for name, value in named_values.items():
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be in the range [0, 1].")
