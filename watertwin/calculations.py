"""Analytical reverse-osmosis reference calculations (API side).

This module is a deliberately *simple, closed-form* implementation of the core
RO physics that the S3M-WaterTwin API uses for quick energy/quality estimates
(e.g. when scoring health or annotating recommendation packets).

It is intentionally an **independent** implementation of the same physics that
the ``treatment-sim`` process-simulation service solves with the WaterTAP/IDAES
stack (or its analytical fallback). The two are expected to agree within a
modest tolerance; a larger divergence is a *bug signal*, not an accepted
difference. The two implementations differ in numerical method:

* Here: a single average-element (lumped) solve using mean-concentration
  osmotic pressure.
* ``treatment-sim``: a discretized multi-segment membrane integration and/or a
  full WaterTAP flowsheet.

All quantities use practical field units (m3/h, bar, mg/L, deg C, kWh/m3).

References for the underlying relations:

* Solution-diffusion flux model (water flux ``Jw = A*(dP - d_pi)``, salt flux
  ``Js = B*dC``) -- standard membrane-transport theory.
* van 't Hoff osmotic pressure for NaCl-equivalent salinity.
"""

from __future__ import annotations

from dataclasses import dataclass

# van 't Hoff osmotic-pressure constant for NaCl (i=2, M=58.44 g/mol,
# R=0.083145 L*bar/mol/K): pi[bar] = K_OSMOTIC * C[g/L] * T[K].
_NACL_MW = 58.44
_R_L_BAR = 0.083145
_VANT_HOFF_I = 2.0
K_OSMOTIC = _VANT_HOFF_I * _R_L_BAR / _NACL_MW  # ~0.002846 bar / (g/L * K)


def osmotic_pressure_bar(tds_mg_l: float, temperature_c: float = 25.0) -> float:
    """Osmotic pressure (bar) of a NaCl-equivalent solution via van 't Hoff."""
    c_g_l = tds_mg_l / 1000.0
    t_k = temperature_c + 273.15
    return K_OSMOTIC * c_g_l * t_k


@dataclass
class ROReference:
    """Result of the analytical RO reference calculation."""

    recovery: float
    permeate_flow_m3h: float
    concentrate_flow_m3h: float
    permeate_tds_mg_l: float
    concentrate_tds_mg_l: float
    salt_rejection: float
    specific_energy_kwh_m3: float
    net_driving_pressure_bar: float
    feed_osmotic_pressure_bar: float
    water_flux_lmh: float


def _concentration_polarization() -> float:
    """Concentration-polarization factor beta (wall/bulk concentration)."""
    return 1.10


def ro_performance(
    feed_flow_m3h: float,
    feed_tds_mg_l: float,
    feed_pressure_bar: float,
    membrane_area_m2: float,
    a_lmh_bar: float = 3.0,
    b_lmh: float = 0.15,
    temperature_c: float = 25.0,
    pump_efficiency: float = 0.8,
    erd_efficiency: float = 0.95,
    use_erd: bool = True,
    pressure_drop_bar: float = 1.0,
) -> ROReference:
    """Compute baseline RO performance with a lumped average-element model.

    A fixed-point iteration closes the coupling between recovery (which raises
    the concentrate-side osmotic pressure) and water flux.
    """
    beta = _concentration_polarization()
    pi_feed = osmotic_pressure_bar(feed_tds_mg_l, temperature_c)

    # Fixed-point on recovery. Mean concentration factor across the element is
    # the average of feed (1x) and concentrate (~1/(1-r)) concentrations.
    recovery = 0.4
    for _ in range(100):
        cf_mean = 0.5 * (1.0 + 1.0 / max(1e-6, (1.0 - recovery)))
        pi_mean = pi_feed * cf_mean * beta
        ndp = feed_pressure_bar - 0.5 * pressure_drop_bar - pi_mean
        ndp = max(ndp, 0.0)
        jw = a_lmh_bar * ndp  # LMH
        permeate_flow_m3h = jw * membrane_area_m2 / 1000.0
        new_recovery = min(0.95, permeate_flow_m3h / feed_flow_m3h)
        if abs(new_recovery - recovery) < 1e-6:
            recovery = new_recovery
            break
        recovery = 0.5 * recovery + 0.5 * new_recovery

    cf_mean = 0.5 * (1.0 + 1.0 / max(1e-6, (1.0 - recovery)))
    pi_mean = pi_feed * cf_mean * beta
    ndp = max(feed_pressure_bar - 0.5 * pressure_drop_bar - pi_mean, 0.0)
    jw = a_lmh_bar * ndp
    permeate_flow_m3h = jw * membrane_area_m2 / 1000.0
    concentrate_flow_m3h = feed_flow_m3h - permeate_flow_m3h

    # Salt transport: Js = B * (wall concentration - permeate concentration).
    # Permeate concentration is small, so approximate dC by the mean wall value.
    c_mean_g_l = (feed_tds_mg_l / 1000.0) * cf_mean * beta
    js = b_lmh * c_mean_g_l  # g/m2/h
    if permeate_flow_m3h > 1e-9:
        permeate_tds_mg_l = js * membrane_area_m2 / permeate_flow_m3h
    else:
        permeate_tds_mg_l = feed_tds_mg_l
    permeate_tds_mg_l = min(permeate_tds_mg_l, feed_tds_mg_l)

    # Concentrate salinity from a whole-system salt mass balance.
    if concentrate_flow_m3h > 1e-9:
        concentrate_tds_mg_l = (
            feed_tds_mg_l * feed_flow_m3h - permeate_tds_mg_l * permeate_flow_m3h
        ) / concentrate_flow_m3h
    else:
        concentrate_tds_mg_l = feed_tds_mg_l
    salt_rejection = 1.0 - permeate_tds_mg_l / feed_tds_mg_l

    specific_energy_kwh_m3 = specific_energy(
        feed_flow_m3h=feed_flow_m3h,
        feed_pressure_bar=feed_pressure_bar,
        recovery=recovery,
        pump_efficiency=pump_efficiency,
        erd_efficiency=erd_efficiency,
        use_erd=use_erd,
        pressure_drop_bar=pressure_drop_bar,
    )

    return ROReference(
        recovery=recovery,
        permeate_flow_m3h=permeate_flow_m3h,
        concentrate_flow_m3h=concentrate_flow_m3h,
        permeate_tds_mg_l=permeate_tds_mg_l,
        concentrate_tds_mg_l=concentrate_tds_mg_l,
        salt_rejection=salt_rejection,
        specific_energy_kwh_m3=specific_energy_kwh_m3,
        net_driving_pressure_bar=ndp,
        feed_osmotic_pressure_bar=pi_feed,
        water_flux_lmh=jw,
    )


def specific_energy(
    feed_flow_m3h: float,
    feed_pressure_bar: float,
    recovery: float,
    pump_efficiency: float = 0.8,
    erd_efficiency: float = 0.95,
    use_erd: bool = True,
    pressure_drop_bar: float = 1.0,
) -> float:
    """Specific energy consumption (kWh/m3 of permeate).

    Hydraulic pump power for flow ``Q`` (m3/h) at pressure ``P`` (bar) is
    ``Q*P/(36*eff)`` kW. When an energy-recovery device is present, the
    concentrate stream returns ``erd_efficiency`` of its pressure energy.
    """
    if recovery <= 0:
        return float("inf")
    permeate_flow = feed_flow_m3h * recovery
    concentrate_flow = feed_flow_m3h * (1.0 - recovery)
    concentrate_pressure = max(feed_pressure_bar - pressure_drop_bar, 0.0)

    gross = feed_flow_m3h * feed_pressure_bar
    recovered = 0.0
    if use_erd:
        recovered = erd_efficiency * concentrate_flow * concentrate_pressure
    net_power_kw = max(gross - recovered, 0.0) / (36.0 * pump_efficiency)
    return net_power_kw / permeate_flow
