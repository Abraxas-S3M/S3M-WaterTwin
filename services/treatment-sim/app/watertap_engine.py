"""WaterTAP/IDAES RO flowsheet engine (open-source process simulation).

This module wraps the open-source WaterTAP (``watertap``) + IDAES (``idaes-pse``)
+ Pyomo (``pyomo``) stack to solve a 0-D reverse-osmosis unit. It is used only
inside the ``treatment-sim`` container, where the ``ipopt`` NLP solver is
installed via the Dockerfile. The WaterTAP repository is *not* vendored; the
pinned PyPI packages are declared in ``requirements.txt`` and recorded in the
open-source register.

Everything here is guarded: if the stack or solver is unavailable, or the solve
does not converge, callers fall back to the analytical model in
:mod:`app.ro_model`. WaterTAP output must agree with the analytical reference
within tolerance -- a divergence is a bug signal, not an accepted difference.

The service is strictly read-only what-if / optimization. Nothing here writes
to any control system.
"""

from __future__ import annotations

import logging

from simulation_contracts import ROBaselineResult

from .ro_model import osmotic_pressure_bar

logger = logging.getLogger("treatment-sim.watertap")


def watertap_available() -> bool:
    """True if the WaterTAP + IDAES + Pyomo stack can be imported."""
    try:
        import idaes  # noqa: F401
        import pyomo.environ  # noqa: F401
        import watertap  # noqa: F401
    except Exception:  # pragma: no cover - depends on container contents
        return False
    return True


def solver_available() -> bool:
    """True if an NLP solver (ipopt) usable by Pyomo is available."""
    if not watertap_available():
        return False
    try:  # pragma: no cover - depends on container contents
        from pyomo.environ import SolverFactory

        solver = SolverFactory("ipopt")
        return bool(solver.available(exception_flag=False))
    except Exception:
        return False


def engine_status() -> str:
    """Return the engine that will actually be used: ``watertap`` or ``analytical``."""
    return "watertap" if solver_available() else "analytical"


def simulate_ro_watertap(
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
) -> ROBaselineResult:  # pragma: no cover - requires WaterTAP + ipopt in container
    """Solve a 0-D RO unit with WaterTAP and return normalized field metrics.

    Raises if the stack/solver are unavailable or the solve fails, so the caller
    can fall back to the analytical model.
    """
    if not solver_available():
        raise RuntimeError("WaterTAP/ipopt not available in this environment")

    from idaes.core import FlowsheetBlock
    from idaes.core.solvers import get_solver
    from pyomo.environ import ConcreteModel, TransformationFactory, units as pyunits
    from watertap.core.solvers import get_solver as wt_get_solver  # noqa: F401
    from watertap.property_models.NaCl_prop_pack import NaClParameterBlock
    from watertap.unit_models.reverse_osmosis_0D import (
        ConcentrationPolarizationType,
        MassTransferCoefficient,
        ReverseOsmosis0D,
    )

    # --- Unit conversions to SI (kg/s, Pa, K, dimensionless mass fractions) ---
    density = 1000.0  # kg/m3 (dilute approximation; WaterTAP refines internally)
    feed_mass_flow = feed_flow_m3h * density / 3600.0  # kg/s
    mass_frac_nacl = feed_tds_mg_l / 1e6  # mg/L over ~1e6 mg/kg
    mass_frac_h2o = 1.0 - mass_frac_nacl
    applied_pa = feed_pressure_bar * 1e5
    temp_k = temperature_c + 273.15

    # A in LMH/bar -> m/s/Pa ; B in LMH -> m/s
    a_si = a_lmh_bar / (1000.0 * 3600.0) / 1e5
    b_si = b_lmh / (1000.0 * 3600.0)

    model = ConcreteModel()
    model.fs = FlowsheetBlock(dynamic=False)
    model.fs.properties = NaClParameterBlock()
    model.fs.ro = ReverseOsmosis0D(
        property_package=model.fs.properties,
        has_pressure_change=True,
        concentration_polarization_type=ConcentrationPolarizationType.calculated,
        mass_transfer_coefficient=MassTransferCoefficient.calculated,
    )

    ro = model.fs.ro
    ro.inlet.flow_mass_phase_comp[0, "Liq", "NaCl"].fix(feed_mass_flow * mass_frac_nacl)
    ro.inlet.flow_mass_phase_comp[0, "Liq", "H2O"].fix(feed_mass_flow * mass_frac_h2o)
    ro.inlet.pressure[0].fix(applied_pa)
    ro.inlet.temperature[0].fix(temp_k)
    ro.area.fix(membrane_area_m2)
    ro.A_comp.fix(a_si)
    ro.B_comp.fix(b_si)
    ro.permeate.pressure[0].fix(101325)
    ro.deltaP.fix(-pressure_drop_bar * 1e5)
    ro.feed_side.channel_height.fix(1e-3)
    ro.feed_side.spacer_porosity.fix(0.97)

    model.fs.properties.set_default_scaling(
        "flow_mass_phase_comp", 1, index=("Liq", "H2O")
    )
    model.fs.properties.set_default_scaling(
        "flow_mass_phase_comp", 1e2, index=("Liq", "NaCl")
    )
    from idaes.core.util.scaling import calculate_scaling_factors

    calculate_scaling_factors(model)
    model.fs.ro.initialize()
    TransformationFactory("network.expand_arcs").apply_to(model)

    solver = get_solver()
    results = solver.solve(model)
    if str(results.solver.termination_condition) != "optimal":
        raise RuntimeError(f"WaterTAP solve non-optimal: {results.solver}")

    perm_h2o = ro.permeate.flow_mass_phase_comp[0, "Liq", "H2O"].value
    perm_nacl = ro.permeate.flow_mass_phase_comp[0, "Liq", "NaCl"].value
    permeate_mass = perm_h2o + perm_nacl
    permeate_flow_m3h = permeate_mass / density * 3600.0
    recovery = permeate_flow_m3h / feed_flow_m3h
    concentrate_flow_m3h = feed_flow_m3h - permeate_flow_m3h
    permeate_tds_mg_l = (perm_nacl / permeate_mass) * 1e6 if permeate_mass else 0.0
    permeate_tds_mg_l = min(permeate_tds_mg_l, feed_tds_mg_l)
    salt_rejection = 1.0 - permeate_tds_mg_l / feed_tds_mg_l
    if concentrate_flow_m3h > 1e-9:
        concentrate_tds_mg_l = (
            feed_tds_mg_l * feed_flow_m3h - permeate_tds_mg_l * permeate_flow_m3h
        ) / concentrate_flow_m3h
    else:
        concentrate_tds_mg_l = feed_tds_mg_l

    from .ro_model import specific_energy_kwh_m3

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
    avg_flux = (permeate_flow_m3h * 1000.0) / membrane_area_m2 if membrane_area_m2 else 0.0

    return ROBaselineResult(
        recovery=recovery,
        permeate_flow_m3h=permeate_flow_m3h,
        concentrate_flow_m3h=concentrate_flow_m3h,
        permeate_tds_mg_l=permeate_tds_mg_l,
        concentrate_tds_mg_l=concentrate_tds_mg_l,
        salt_rejection=salt_rejection,
        specific_energy_kwh_m3=sec,
        net_driving_pressure_bar=max(feed_pressure_bar - pi_feed, 0.0),
        feed_osmotic_pressure_bar=pi_feed,
        water_flux_lmh=avg_flux,
        engine="watertap",
    )
