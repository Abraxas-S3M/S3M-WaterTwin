"""Whole-train RO evaluation.

Combines the individual deterministic calculations into a single, coherent
snapshot of one seawater RO train. The result is a plain, immutable value
object; mapping it into API/analytics schemas happens elsewhere. This keeps the
physics engine free of transport and presentation concerns.
"""

from __future__ import annotations

from dataclasses import dataclass

from watertwin_engineering.osmotic import seawater_osmotic_pressure_bar
from watertwin_engineering.ro import (
    concentration_factor,
    net_driving_pressure_bar,
    recovery_fraction,
    salt_passage_fraction,
    salt_rejection_fraction,
    specific_energy_consumption_kwh_per_m3,
    temperature_correction_factor,
    water_flux_lmh,
)


@dataclass(frozen=True, slots=True)
class TrainEvaluation:
    """Immutable snapshot of derived RO-train performance metrics.

    All values are deterministic engineering estimates. Concentrations are in
    mg/L, pressures in bar, flows in m^3/h, flux in LMH, and SEC in kWh/m^3.
    """

    recovery_fraction: float
    salt_rejection_fraction: float
    salt_passage_fraction: float
    concentration_factor: float
    feed_osmotic_pressure_bar: float
    concentrate_osmotic_pressure_bar: float
    average_feed_side_osmotic_pressure_bar: float
    permeate_osmotic_pressure_bar: float
    net_driving_pressure_bar: float
    water_flux_lmh: float
    temperature_correction_factor: float
    normalized_permeate_flow_m3_per_h: float
    specific_energy_consumption_kwh_per_m3: float


def evaluate_train(
    *,
    feed_pressure_bar: float,
    permeate_pressure_bar: float,
    feed_flow_m3_per_h: float,
    permeate_flow_m3_per_h: float,
    feed_tds_mg_per_l: float,
    permeate_tds_mg_per_l: float,
    temperature_c: float,
    membrane_permeability_lmh_per_bar: float,
    feed_channel_dp_bar: float = 0.0,
    pump_efficiency: float = 0.8,
    energy_recovery_efficiency: float = 0.0,
) -> TrainEvaluation:
    """Evaluate one RO train from a single synthetic telemetry snapshot.

    Args:
        feed_pressure_bar: High-pressure pump discharge pressure, bar.
        permeate_pressure_bar: Permeate back-pressure, bar.
        feed_flow_m3_per_h: Feed flow to the membranes, m^3/h.
        permeate_flow_m3_per_h: Permeate production, m^3/h.
        feed_tds_mg_per_l: Feed total dissolved solids, mg/L.
        permeate_tds_mg_per_l: Permeate total dissolved solids, mg/L.
        temperature_c: Feed temperature, degrees Celsius.
        membrane_permeability_lmh_per_bar: Water permeability ``A``.
        feed_channel_dp_bar: Feed-to-concentrate friction pressure drop, bar.
        pump_efficiency: High-pressure pump efficiency, fraction in (0, 1].
        energy_recovery_efficiency: ERD efficiency, fraction in [0, 1].

    Returns:
        A :class:`TrainEvaluation` snapshot.

    Raises:
        ValueError: Propagated from the underlying calculations for any invalid
            input (see each function's contract).
    """

    recovery = recovery_fraction(permeate_flow_m3_per_h, feed_flow_m3_per_h)
    rejection = salt_rejection_fraction(feed_tds_mg_per_l, permeate_tds_mg_per_l)
    passage = salt_passage_fraction(feed_tds_mg_per_l, permeate_tds_mg_per_l)
    cf = concentration_factor(recovery, rejection)

    concentrate_tds_mg_per_l = feed_tds_mg_per_l * cf

    feed_osmotic = seawater_osmotic_pressure_bar(feed_tds_mg_per_l, temperature_c)
    concentrate_osmotic = seawater_osmotic_pressure_bar(concentrate_tds_mg_per_l, temperature_c)
    average_feed_side_osmotic = (feed_osmotic + concentrate_osmotic) / 2.0
    permeate_osmotic = seawater_osmotic_pressure_bar(permeate_tds_mg_per_l, temperature_c)

    ndp = net_driving_pressure_bar(
        feed_pressure_bar=feed_pressure_bar,
        permeate_pressure_bar=permeate_pressure_bar,
        feed_side_osmotic_bar=average_feed_side_osmotic,
        permeate_osmotic_bar=permeate_osmotic,
        feed_channel_dp_bar=feed_channel_dp_bar,
    )
    flux = water_flux_lmh(membrane_permeability_lmh_per_bar, ndp)

    tcf = temperature_correction_factor(temperature_c)
    normalized_permeate_flow = permeate_flow_m3_per_h * tcf

    sec = specific_energy_consumption_kwh_per_m3(
        feed_pressure_bar=feed_pressure_bar,
        feed_flow_m3_per_h=feed_flow_m3_per_h,
        permeate_flow_m3_per_h=permeate_flow_m3_per_h,
        pump_efficiency=pump_efficiency,
        energy_recovery_efficiency=energy_recovery_efficiency,
    )

    return TrainEvaluation(
        recovery_fraction=recovery,
        salt_rejection_fraction=rejection,
        salt_passage_fraction=passage,
        concentration_factor=cf,
        feed_osmotic_pressure_bar=feed_osmotic,
        concentrate_osmotic_pressure_bar=concentrate_osmotic,
        average_feed_side_osmotic_pressure_bar=average_feed_side_osmotic,
        permeate_osmotic_pressure_bar=permeate_osmotic,
        net_driving_pressure_bar=ndp,
        water_flux_lmh=flux,
        temperature_correction_factor=tcf,
        normalized_permeate_flow_m3_per_h=normalized_permeate_flow,
        specific_energy_consumption_kwh_per_m3=sec,
    )
