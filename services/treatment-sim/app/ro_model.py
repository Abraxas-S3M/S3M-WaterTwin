"""Analytical reverse-osmosis model (discretized multi-segment method).

This is the service-side physics implementation. It solves the RO element as a
sequence of ``N`` finite membrane segments, marching along the feed channel and
integrating water and salt transport. This is deliberately a *different
numerical method* from ``watertwin.calculations`` (a single lumped average
element), so the two act as an independent cross-check of the same physics.

When the WaterTAP/IDAES stack and a solver are available, the service prefers
the WaterTAP flowsheet (see :mod:`app.watertap_engine`); this analytical model
is the always-available fallback and the reference used in tests.

Units: m3/h, bar, mg/L, deg C, kWh/m3.
"""

from __future__ import annotations

from simulation_contracts import ROBaselineResult

# The osmotic-pressure relation and the lumped specific-energy calculation are
# the single canonical implementations from the shared physics package. This
# service contributes only its *distinct numerical method* (the discretized
# multi-segment marching solve below), never a duplicate of the shared physics.
from watertwin_engineering import osmotic_pressure_bar
from watertwin_engineering.calculations import specific_energy as specific_energy_kwh_m3

__all__ = ["osmotic_pressure_bar", "specific_energy_kwh_m3", "simulate_ro"]

_BETA = 1.10  # concentration-polarization factor (wall / bulk)
_N_SEGMENTS = 200


def simulate_ro(
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
    n_segments: int = _N_SEGMENTS,
    engine_label: str = "analytical",
) -> ROBaselineResult:
    """Solve a single RO stage by marching along ``n_segments`` membrane slices."""
    d_area = membrane_area_m2 / n_segments
    dp_per_segment = pressure_drop_bar / n_segments

    q = feed_flow_m3h  # local bulk feed flow (m3/h)
    # Salt throughput tracked in (g/L * m3/h); dividing by flow recovers g/L.
    salt_flow = (feed_tds_mg_l / 1000.0) * feed_flow_m3h
    pressure = feed_pressure_bar

    permeate_flow = 0.0
    permeate_salt = 0.0  # units: g/L * m3/h

    for _ in range(n_segments):
        if q <= 1e-9:
            break
        c_bulk = salt_flow / q  # g/L
        c_wall = c_bulk * _BETA
        # c_wall is g/L; the canonical osmotic function takes mg/L.
        pi_local = osmotic_pressure_bar(c_wall * 1000.0, temperature_c)
        ndp = max(pressure - pi_local, 0.0)
        jw = a_lmh_bar * ndp  # LMH
        dqp = jw * d_area / 1000.0  # m3/h
        dqp = min(dqp, q)  # cannot draw more than local flow

        js = b_lmh * c_wall  # g/m2/h
        dsalt = js * d_area / 1000.0  # (g/m2/h)*(m2)/1000 -> g/L*m3/h equivalent

        permeate_flow += dqp
        permeate_salt += dsalt
        q -= dqp
        salt_flow = max(salt_flow - dsalt, 0.0)
        pressure -= dp_per_segment

    concentrate_flow = feed_flow_m3h - permeate_flow
    recovery = permeate_flow / feed_flow_m3h if feed_flow_m3h > 0 else 0.0

    if permeate_flow > 1e-9:
        permeate_tds_mg_l = (permeate_salt / permeate_flow) * 1000.0
    else:
        permeate_tds_mg_l = feed_tds_mg_l
    permeate_tds_mg_l = min(permeate_tds_mg_l, feed_tds_mg_l)

    if concentrate_flow > 1e-9:
        concentrate_tds_mg_l = (salt_flow / concentrate_flow) * 1000.0
    else:
        concentrate_tds_mg_l = feed_tds_mg_l

    salt_rejection = 1.0 - permeate_tds_mg_l / feed_tds_mg_l

    sec = specific_energy_kwh_m3(
        feed_flow_m3h=feed_flow_m3h,
        feed_pressure_bar=feed_pressure_bar,
        recovery=recovery,
        pump_efficiency=pump_efficiency,
        erd_efficiency=erd_efficiency,
        use_erd=use_erd,
        pressure_drop_bar=pressure_drop_bar,
    )

    pi_feed = osmotic_pressure_bar(feed_tds_mg_l, temperature_c)
    avg_flux = (permeate_flow * 1000.0) / membrane_area_m2 if membrane_area_m2 else 0.0
    ndp_overall = max(
        feed_pressure_bar - 0.5 * pressure_drop_bar - pi_feed * _BETA, 0.0
    )

    return ROBaselineResult(
        recovery=recovery,
        permeate_flow_m3h=permeate_flow,
        concentrate_flow_m3h=concentrate_flow,
        permeate_tds_mg_l=permeate_tds_mg_l,
        concentrate_tds_mg_l=concentrate_tds_mg_l,
        salt_rejection=salt_rejection,
        specific_energy_kwh_m3=sec,
        net_driving_pressure_bar=ndp_overall,
        feed_osmotic_pressure_bar=pi_feed,
        water_flux_lmh=avg_flux,
        engine=engine_label,
    )
