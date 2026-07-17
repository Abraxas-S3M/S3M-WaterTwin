"""Deterministic reverse-osmosis membrane calculations.

All functions are pure and validate their inputs. Units are stated explicitly in
every signature. These are engineering approximations for advisory, preliminary
analytics -- not laboratory-validated predictions.
"""

from __future__ import annotations

import math

from watertwin.engineering.constants import (
    PASCAL_PER_BAR,
    REFERENCE_TEMPERATURE_C,
    SECONDS_PER_HOUR,
    TEMPERATURE_CORRECTION_COEFFICIENT_PER_C,
)


def net_driving_pressure_bar(
    feed_pressure_bar: float,
    permeate_pressure_bar: float,
    feed_side_osmotic_bar: float,
    permeate_osmotic_bar: float,
    feed_channel_dp_bar: float = 0.0,
) -> float:
    """Net driving pressure (NDP) across the membrane, in bar.

    ``NDP = (P_feed - dP_channel/2) - P_permeate - (pi_feed_side - pi_permeate)``.

    The feed-channel pressure drop is halved to approximate the average
    hydraulic pressure along the pressure vessel.

    Args:
        feed_pressure_bar: Applied feed pressure, bar (>= 0).
        permeate_pressure_bar: Permeate-side back-pressure, bar (>= 0).
        feed_side_osmotic_bar: Average feed/concentrate osmotic pressure, bar
            (>= 0).
        permeate_osmotic_bar: Permeate osmotic pressure, bar (>= 0).
        feed_channel_dp_bar: Feed-to-concentrate friction pressure drop, bar
            (>= 0).

    Returns:
        Net driving pressure in bar. May be negative or zero when the applied
        pressure does not overcome the osmotic pressure (no net production).

    Raises:
        ValueError: If any argument is negative.
    """

    _require_non_negative(feed_pressure_bar=feed_pressure_bar)
    _require_non_negative(permeate_pressure_bar=permeate_pressure_bar)
    _require_non_negative(feed_side_osmotic_bar=feed_side_osmotic_bar)
    _require_non_negative(permeate_osmotic_bar=permeate_osmotic_bar)
    _require_non_negative(feed_channel_dp_bar=feed_channel_dp_bar)

    average_feed_pressure = feed_pressure_bar - feed_channel_dp_bar / 2.0
    net_osmotic = feed_side_osmotic_bar - permeate_osmotic_bar
    return average_feed_pressure - permeate_pressure_bar - net_osmotic


def water_flux_lmh(permeability_lmh_per_bar: float, net_driving_pressure_bar: float) -> float:
    """Membrane water flux from the solution-diffusion model.

    ``Jw = A * NDP`` where ``A`` is the water-permeability coefficient. Flux is
    clamped at zero: a non-positive net driving pressure produces no permeate.

    Args:
        permeability_lmh_per_bar: Water permeability ``A``, in L/(m^2*h*bar)
            (> 0).
        net_driving_pressure_bar: Net driving pressure, bar.

    Returns:
        Water flux in LMH (L/(m^2*h)), never negative.

    Raises:
        ValueError: If permeability is not positive.
    """

    if permeability_lmh_per_bar <= 0:
        raise ValueError("permeability_lmh_per_bar must be positive.")
    return max(0.0, permeability_lmh_per_bar * net_driving_pressure_bar)


def recovery_fraction(permeate_flow: float, feed_flow: float) -> float:
    """System recovery ``r = Q_permeate / Q_feed`` as a fraction in [0, 1].

    Flow units are arbitrary but must match. Recovery cannot exceed unity.

    Raises:
        ValueError: If feed flow is not positive, flows are negative, or the
            implied recovery exceeds 1.
    """

    if feed_flow <= 0:
        raise ValueError("feed_flow must be positive.")
    if permeate_flow < 0:
        raise ValueError("permeate_flow must be non-negative.")
    recovery = permeate_flow / feed_flow
    if recovery > 1.0:
        raise ValueError("permeate_flow cannot exceed feed_flow (recovery > 1).")
    return recovery


def salt_passage_fraction(feed_tds_mg_per_l: float, permeate_tds_mg_per_l: float) -> float:
    """Observed salt passage ``SP = C_permeate / C_feed`` as a fraction in [0, 1].

    Raises:
        ValueError: If feed TDS is not positive, permeate TDS is negative, or
            permeate TDS exceeds feed TDS (passage > 1).
    """

    if feed_tds_mg_per_l <= 0:
        raise ValueError("feed_tds_mg_per_l must be positive.")
    if permeate_tds_mg_per_l < 0:
        raise ValueError("permeate_tds_mg_per_l must be non-negative.")
    passage = permeate_tds_mg_per_l / feed_tds_mg_per_l
    if passage > 1.0:
        raise ValueError("permeate_tds cannot exceed feed_tds (salt passage > 1).")
    return passage


def salt_rejection_fraction(feed_tds_mg_per_l: float, permeate_tds_mg_per_l: float) -> float:
    """Observed salt rejection ``R_s = 1 - SP`` as a fraction in [0, 1]."""

    return 1.0 - salt_passage_fraction(feed_tds_mg_per_l, permeate_tds_mg_per_l)


def concentration_factor(recovery: float, salt_rejection: float) -> float:
    """Concentrate/feed concentration ratio ``CF = Cc / Cf``.

    Derived from a steady-state mass balance:
    ``CF = (1 - r * (1 - R_s)) / (1 - r)``.

    Args:
        recovery: System recovery fraction ``r`` in [0, 1).
        salt_rejection: Observed salt rejection fraction ``R_s`` in [0, 1].

    Returns:
        Dimensionless concentration factor (>= 1).

    Raises:
        ValueError: If ``recovery`` is outside [0, 1) or ``salt_rejection`` is
            outside [0, 1].
    """

    if not 0.0 <= recovery < 1.0:
        raise ValueError("recovery must be in the range [0, 1).")
    if not 0.0 <= salt_rejection <= 1.0:
        raise ValueError("salt_rejection must be in the range [0, 1].")
    salt_passage = 1.0 - salt_rejection
    return (1.0 - recovery * salt_passage) / (1.0 - recovery)


def temperature_correction_factor(
    temperature_c: float,
    reference_temperature_c: float = REFERENCE_TEMPERATURE_C,
    coefficient_per_c: float = TEMPERATURE_CORRECTION_COEFFICIENT_PER_C,
) -> float:
    """Temperature-correction factor (TCF) for normalising permeate flow.

    Uses the common exponential approximation
    ``TCF = exp(-k * (T - T_ref))`` so that measured flow can be normalised to
    the reference temperature by multiplication. Below the reference the factor
    exceeds 1 (cold water permeates less, so measured flow is scaled up).

    Args:
        temperature_c: Actual stream temperature, degrees Celsius.
        reference_temperature_c: Normalisation reference, degrees Celsius.
        coefficient_per_c: Temperature sensitivity ``k`` per degree C (> 0).

    Returns:
        Dimensionless correction factor (> 0).

    Raises:
        ValueError: If the coefficient is not positive.
    """

    if coefficient_per_c <= 0:
        raise ValueError("coefficient_per_c must be positive.")
    return math.exp(-coefficient_per_c * (temperature_c - reference_temperature_c))


def specific_energy_consumption_kwh_per_m3(
    feed_pressure_bar: float,
    feed_flow_m3_per_h: float,
    permeate_flow_m3_per_h: float,
    pump_efficiency: float,
    energy_recovery_efficiency: float = 0.0,
    concentrate_pressure_bar: float | None = None,
) -> float:
    """Specific energy consumption (SEC) of the high-pressure pump, kWh/m^3.

    Hydraulic power delivered to the feed is ``P_feed * Q_feed`` (converted to
    SI), divided by the pump efficiency. An energy-recovery device (ERD) can
    recover part of the pressure energy still present in the concentrate stream;
    its recovered power is subtracted. SEC is that net electrical power divided
    by the permeate production rate.

    Args:
        feed_pressure_bar: High-pressure pump discharge pressure, bar (>= 0).
        feed_flow_m3_per_h: Feed flow to the membranes, m^3/h (> 0).
        permeate_flow_m3_per_h: Permeate production, m^3/h (> 0).
        pump_efficiency: High-pressure pump efficiency, fraction in (0, 1].
        energy_recovery_efficiency: ERD efficiency, fraction in [0, 1].
        concentrate_pressure_bar: Concentrate pressure available to the ERD,
            bar. Defaults to ``feed_pressure_bar`` when ``None``.

    Returns:
        Specific energy consumption in kWh per m^3 of permeate (>= 0).

    Raises:
        ValueError: If any argument is outside its valid range.
    """

    _require_non_negative(feed_pressure_bar=feed_pressure_bar)
    if feed_flow_m3_per_h <= 0:
        raise ValueError("feed_flow_m3_per_h must be positive.")
    if permeate_flow_m3_per_h <= 0:
        raise ValueError("permeate_flow_m3_per_h must be positive.")
    if permeate_flow_m3_per_h > feed_flow_m3_per_h:
        raise ValueError("permeate_flow_m3_per_h cannot exceed feed_flow_m3_per_h.")
    if not 0.0 < pump_efficiency <= 1.0:
        raise ValueError("pump_efficiency must be in the range (0, 1].")
    if not 0.0 <= energy_recovery_efficiency <= 1.0:
        raise ValueError("energy_recovery_efficiency must be in the range [0, 1].")
    if concentrate_pressure_bar is None:
        concentrate_pressure_bar = feed_pressure_bar
    _require_non_negative(concentrate_pressure_bar=concentrate_pressure_bar)

    feed_pressure_pa = feed_pressure_bar * PASCAL_PER_BAR
    concentrate_pressure_pa = concentrate_pressure_bar * PASCAL_PER_BAR

    feed_flow_m3_per_s = feed_flow_m3_per_h / SECONDS_PER_HOUR
    concentrate_flow_m3_per_s = (feed_flow_m3_per_h - permeate_flow_m3_per_h) / SECONDS_PER_HOUR

    pump_power_w = feed_pressure_pa * feed_flow_m3_per_s / pump_efficiency
    recovered_power_w = (
        concentrate_pressure_pa * concentrate_flow_m3_per_s * energy_recovery_efficiency
    )
    net_power_w = max(0.0, pump_power_w - recovered_power_w)

    net_power_kw = net_power_w / 1000.0
    # kW divided by (m^3/h) yields kWh/m^3 directly.
    return net_power_kw / permeate_flow_m3_per_h


def _require_non_negative(**named_values: float) -> None:
    """Raise ``ValueError`` if any provided value is negative."""

    for name, value in named_values.items():
        if value < 0:
            raise ValueError(f"{name} must be non-negative.")
