"""Deterministic engineering calculation library for the S3M WaterTwin.

This module is the single source of truth for the physics and hydraulics of a
seawater reverse-osmosis (SWRO) desalination train. Every value that describes
"real" behaviour of pumps, membranes and energy-recovery devices must be
computed here from first principles so that higher layers (including any ML or
LLM component) consume validated numbers instead of inventing them.

Design rules for every public function:
* Named inputs with the physical unit baked into the parameter name.
* Explicit unit in the return-value documentation.
* Input validation that raises :class:`CalcError` on physically impossible or
  numerically unsafe arguments.
* A docstring that records the engineering basis (formula and references).

Nothing in this module uses machine learning or fitted coefficients without an
explicit basis note.
"""

from __future__ import annotations

import math
from typing import Any

# --------------------------------------------------------------------------- #
# Physical constants (documented basis, not fitted).
# --------------------------------------------------------------------------- #
G = 9.80665  # Standard gravitational acceleration, m/s^2 (ISO 80000-3).
BAR_TO_PA = 1e5  # 1 bar = 100 000 Pa (exact, SI definition of the bar).
NACL_MW_G_PER_MOL = 58.44  # Molar mass of NaCl, g/mol.
VANT_HOFF_I = 2  # van't Hoff factor for fully dissociated NaCl (Na+ + Cl-).
OSMOTIC_COEFFICIENT_PHI = 0.93  # Practical osmotic coefficient for seawater NaCl.
R_L_BAR_PER_MOL_K = 0.083145  # Universal gas constant, L*bar/(mol*K).
SEAWATER_DENSITY_KG_M3 = 1025.0  # Nominal seawater density at ~25 C, 35 g/L.
KELVIN_OFFSET = 273.15  # 0 C in kelvin.
WATER_VAPOR_PRESSURE_BAR = 0.0317  # Saturated vapour pressure of water at ~25 C, bar(a).

# Reference temperature used for membrane temperature normalisation, kelvin.
_REF_TEMPERATURE_K = 25.0 + KELVIN_OFFSET  # 298.15 K
# Activation-energy style constant for RO temperature correction, kelvin.
# Basis: manufacturer TCF models (e.g. DuPont/FilmTec) use exp(k*(1/T-1/T_ref))
# with k ~ 2640-2700 K for polyamide membranes; 2700 K is used here.
_TCF_ACTIVATION_K = 2700.0


class CalcError(ValueError):
    """Raised when an engineering calculation receives an invalid input.

    Subclasses :class:`ValueError` so that callers that only catch the standard
    exception still behave correctly, while code that cares specifically about
    calculation-domain problems can catch :class:`CalcError`.
    """


def _require(cond: bool, msg: str) -> None:
    """Validate an engineering precondition.

    Raises :class:`CalcError` with ``msg`` when ``cond`` is falsey. Kept tiny so
    that every public function reads as a short list of physical requirements.
    """

    if not cond:
        raise CalcError(msg)


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into the closed interval ``[low, high]``."""

    return max(low, min(high, value))


# --------------------------------------------------------------------------- #
# Pump hydraulics.
# --------------------------------------------------------------------------- #
def pump_head_m(
    suction_bar: float,
    discharge_bar: float,
    rho_kg_m3: float = SEAWATER_DENSITY_KG_M3,
) -> float:
    """Total developed head across a pump, in metres of fluid column.

    Basis: Bernoulli head from a static pressure rise, ``H = dP / (rho * g)``
    with ``dP`` the discharge-minus-suction pressure difference. A pump cannot
    develop negative head, so a discharge pressure below the suction pressure is
    rejected as a sensor/tag error.

    Args:
        suction_bar: Pump suction pressure, bar (gauge or absolute; only the
            difference matters).
        discharge_bar: Pump discharge pressure, same reference as suction, bar.
        rho_kg_m3: Fluid density, kg/m^3 (defaults to seawater).

    Returns:
        Developed head, metres of fluid.
    """

    _require(rho_kg_m3 > 0, "density must be positive")
    _require(
        discharge_bar >= suction_bar,
        "discharge pressure must be >= suction pressure",
    )
    return (discharge_bar - suction_bar) * BAR_TO_PA / (rho_kg_m3 * G)


def hydraulic_power_kw(
    flow_m3h: float,
    head_m: float,
    rho_kg_m3: float = SEAWATER_DENSITY_KG_M3,
) -> float:
    """Hydraulic (fluid) power delivered by a pump, in kilowatts.

    Basis: ``P = rho * g * Q * H``. With flow in m^3/h the conversion factor is
    ``3.6e6`` (3600 s/h * 1000 W/kW), giving ``P[kW] = rho*g*Q*H / 3.6e6``.

    Args:
        flow_m3h: Volumetric flow, m^3/h.
        head_m: Developed head, metres of fluid.
        rho_kg_m3: Fluid density, kg/m^3 (defaults to seawater).

    Returns:
        Hydraulic power, kW.
    """

    _require(rho_kg_m3 > 0, "density must be positive")
    _require(flow_m3h >= 0, "flow must be non-negative")
    return rho_kg_m3 * G * flow_m3h * head_m / 3.6e6


def pump_efficiency(hydraulic_kw: float, shaft_kw: float) -> float:
    """Pump hydraulic efficiency (fraction 0..1).

    Basis: ratio of fluid power out to shaft power in. Physically bounded to
    ``[0, 1]``; measurement noise can push the raw ratio slightly outside that
    range, so the result is clamped.

    Args:
        hydraulic_kw: Hydraulic power delivered to the fluid, kW.
        shaft_kw: Mechanical shaft power into the pump, kW.

    Returns:
        Efficiency, dimensionless fraction in [0, 1].
    """

    _require(shaft_kw > 0, "shaft power must be positive")
    _require(hydraulic_kw >= 0, "hydraulic power must be non-negative")
    return _clamp(hydraulic_kw / shaft_kw, 0.0, 1.0)


def wire_to_water_efficiency(hydraulic_kw: float, motor_input_kw: float) -> float:
    """Overall wire-to-water efficiency of a motor+pump set (fraction 0..1).

    Basis: fluid power out divided by electrical power drawn at the motor
    terminals; captures motor, VFD and pump losses together. Clamped to
    ``[0, 1]``.

    Args:
        hydraulic_kw: Hydraulic power delivered to the fluid, kW.
        motor_input_kw: Electrical input power at the motor terminals, kW.

    Returns:
        Efficiency, dimensionless fraction in [0, 1].
    """

    _require(motor_input_kw > 0, "motor input power must be positive")
    _require(hydraulic_kw >= 0, "hydraulic power must be non-negative")
    return _clamp(hydraulic_kw / motor_input_kw, 0.0, 1.0)


def specific_energy_kwh_m3(power_kw: float, permeate_flow_m3h: float) -> float:
    """Specific energy consumption, kWh per m^3 of permeate.

    Basis: ``SEC = P[kW] / Q[m^3/h]`` yields kW*h/m^3 = kWh/m^3 directly. This
    is the primary KPI for RO energy performance.

    Args:
        power_kw: Power consumed, kW.
        permeate_flow_m3h: Permeate (product) flow, m^3/h.

    Returns:
        Specific energy, kWh/m^3.
    """

    _require(permeate_flow_m3h > 0, "permeate flow must be positive")
    _require(power_kw >= 0, "power must be non-negative")
    return power_kw / permeate_flow_m3h


# --------------------------------------------------------------------------- #
# Cavitation / NPSH.
# --------------------------------------------------------------------------- #
def npsh_margin_m(npsh_available_m: float, npsh_required_m: float) -> float:
    """Net positive suction head margin, metres.

    Basis: ``NPSH_margin = NPSH_available - NPSH_required``. A negative margin
    means the pump is operating below the required suction head and is prone to
    cavitation, so negative results are allowed (they carry meaning).

    Args:
        npsh_available_m: NPSH available at the pump inlet, m.
        npsh_required_m: NPSH required by the pump at duty, m.

    Returns:
        NPSH margin, m (may be negative).
    """

    _require(npsh_required_m >= 0, "NPSH required must be non-negative")
    return npsh_available_m - npsh_required_m


def cavitation_index(
    npsh_margin_m: float,
    vibration_mm_s: float,
    suction_bar: float,
) -> float:
    """Composite cavitation-risk index, dimensionless fraction in [0, 1].

    Higher means more cavitation risk. The index rises as NPSH margin falls, as
    vibration velocity rises, and as suction pressure drops toward the fluid
    vapour pressure. It is, by construction, monotonically *decreasing* in the
    NPSH margin.

    Basis: three normalised risk contributions combined as a weighted sum.
    * NPSH margin risk: ``exp(-max(margin, 0) / 1.0 m)`` -> 1 at zero/negative
      margin, decaying smoothly to 0 as margin grows (1 m scale is a common
      minimum design margin for process pumps).
    * Vibration risk: ``vibration / 7.1 mm/s`` clamped to [0, 1]; 7.1 mm/s RMS is
      the ISO 10816 boundary between "unsatisfactory" and "unacceptable" for
      many medium machines.
    * Suction risk: linear from atmospheric (1 bar, risk 0) down to the vapour
      pressure (risk 1), where flashing/cavitation is certain.
    Weights (0.5 / 0.3 / 0.2) emphasise NPSH margin as the dominant driver while
    still responding to vibration and suction pressure.

    Args:
        npsh_margin_m: NPSH margin, m.
        vibration_mm_s: Pump vibration velocity, mm/s RMS.
        suction_bar: Suction pressure, bar (absolute).

    Returns:
        Cavitation risk index in [0, 1].
    """

    _require(vibration_mm_s >= 0, "vibration must be non-negative")

    margin_scale_m = 1.0
    margin_risk = math.exp(-max(npsh_margin_m, 0.0) / margin_scale_m)

    vibration_limit_mm_s = 7.1
    vibration_risk = _clamp(vibration_mm_s / vibration_limit_mm_s, 0.0, 1.0)

    reference_bar = 1.0
    span = reference_bar - WATER_VAPOR_PRESSURE_BAR
    suction_risk = _clamp((reference_bar - suction_bar) / span, 0.0, 1.0)

    index = 0.5 * margin_risk + 0.3 * vibration_risk + 0.2 * suction_risk
    return _clamp(index, 0.0, 1.0)


def bep_distance(flow_m3h: float, bep_flow_m3h: float) -> float:
    """Relative distance of the operating point from best-efficiency point.

    Basis: ``|Q - Q_bep| / Q_bep``. A dimensionless fraction; 0 means running at
    BEP, 0.2 means 20% away. Used to flag off-BEP operation that increases wear
    and recirculation.

    Args:
        flow_m3h: Actual operating flow, m^3/h.
        bep_flow_m3h: Best-efficiency-point flow, m^3/h.

    Returns:
        Relative distance from BEP, dimensionless (>= 0).
    """

    _require(bep_flow_m3h > 0, "BEP flow must be positive")
    return abs(flow_m3h - bep_flow_m3h) / bep_flow_m3h


# --------------------------------------------------------------------------- #
# Membrane / RO process.
# --------------------------------------------------------------------------- #
def recovery(permeate_flow_m3h: float, feed_flow_m3h: float) -> float:
    """System recovery ratio, dimensionless fraction in [0, 1].

    Basis: ``Y = Q_permeate / Q_feed``. Permeate cannot exceed feed by
    conservation of mass, so that condition is rejected.

    Args:
        permeate_flow_m3h: Permeate (product) flow, m^3/h.
        feed_flow_m3h: Feed flow, m^3/h.

    Returns:
        Recovery ratio in [0, 1].
    """

    _require(feed_flow_m3h > 0, "feed flow must be positive")
    _require(permeate_flow_m3h >= 0, "permeate flow must be non-negative")
    _require(
        permeate_flow_m3h <= feed_flow_m3h,
        "permeate flow cannot exceed feed flow",
    )
    return permeate_flow_m3h / feed_flow_m3h


def concentration_factor(recovery_ratio: float) -> float:
    """Concentration factor of the reject stream, dimensionless.

    Basis: ``CF = 1 / (1 - Y)`` for full salt rejection; approximates how much
    the feed salinity is concentrated in the brine at recovery ``Y``. Undefined
    at 100% recovery.

    Args:
        recovery_ratio: Recovery ratio in [0, 1).

    Returns:
        Concentration factor, dimensionless (>= 1).
    """

    _require(0.0 <= recovery_ratio < 1.0, "recovery must be in [0, 1)")
    return 1.0 / (1.0 - recovery_ratio)


def salt_rejection(feed_tds_mg_l: float, permeate_tds_mg_l: float) -> float:
    """Observed salt rejection, dimensionless fraction in [0, 1].

    Basis: ``R = 1 - C_permeate / C_feed``. Clamped to [0, 1]; a permeate more
    saline than feed (ratio > 1) clamps to 0 rejection.

    Args:
        feed_tds_mg_l: Feed total dissolved solids, mg/L.
        permeate_tds_mg_l: Permeate total dissolved solids, mg/L.

    Returns:
        Salt rejection in [0, 1].
    """

    _require(feed_tds_mg_l > 0, "feed TDS must be positive")
    _require(permeate_tds_mg_l >= 0, "permeate TDS must be non-negative")
    return _clamp(1.0 - permeate_tds_mg_l / feed_tds_mg_l, 0.0, 1.0)


def salt_passage(feed_tds_mg_l: float, permeate_tds_mg_l: float) -> float:
    """Observed salt passage, dimensionless fraction in [0, 1].

    Basis: ``SP = C_permeate / C_feed`` = ``1 - R``, the complement of salt
    rejection. Clamped to [0, 1] so that rejection and passage always sum to 1.

    Args:
        feed_tds_mg_l: Feed total dissolved solids, mg/L.
        permeate_tds_mg_l: Permeate total dissolved solids, mg/L.

    Returns:
        Salt passage in [0, 1].
    """

    _require(feed_tds_mg_l > 0, "feed TDS must be positive")
    _require(permeate_tds_mg_l >= 0, "permeate TDS must be non-negative")
    return _clamp(permeate_tds_mg_l / feed_tds_mg_l, 0.0, 1.0)


def osmotic_pressure_bar(tds_mg_l: float, temperature_c: float = 25.0) -> float:
    """Osmotic pressure of a NaCl-equivalent solution, bar.

    Basis: van't Hoff relation with a practical osmotic coefficient,
    ``pi = phi * i * M * R * T``, where molarity ``M = (TDS[g/L]) / MW`` with
    TDS converted from mg/L via ``/1000``. Using phi=0.93, i=2, MW=58.44 g/mol
    and R=0.083145 L*bar/(mol*K) this yields ~27.6 bar for 35 000 mg/L at 25 C,
    matching standard seawater osmotic pressure.

    Args:
        tds_mg_l: Total dissolved solids, mg/L.
        temperature_c: Temperature, degrees Celsius.

    Returns:
        Osmotic pressure, bar.
    """

    _require(tds_mg_l >= 0, "TDS must be non-negative")
    _require(temperature_c > -KELVIN_OFFSET, "temperature must be above absolute zero")
    molarity = (tds_mg_l / 1000.0) / NACL_MW_G_PER_MOL
    temperature_k = temperature_c + KELVIN_OFFSET
    return (
        OSMOTIC_COEFFICIENT_PHI
        * VANT_HOFF_I
        * molarity
        * R_L_BAR_PER_MOL_K
        * temperature_k
    )


def net_driving_pressure_bar(
    feed_pressure_bar: float,
    permeate_pressure_bar: float,
    feed_osmotic_bar: float,
    permeate_osmotic_bar: float = 0.0,
) -> float:
    """Net driving pressure across the membrane, bar.

    Basis: ``NDP = (P_feed - P_permeate) - (pi_feed - pi_permeate)``, the applied
    hydraulic pressure difference less the opposing osmotic pressure difference.
    May be negative if osmotic pressure exceeds applied pressure (no net flux).

    Args:
        feed_pressure_bar: Feed hydraulic pressure, bar.
        permeate_pressure_bar: Permeate hydraulic pressure, bar.
        feed_osmotic_bar: Feed-side osmotic pressure, bar.
        permeate_osmotic_bar: Permeate-side osmotic pressure, bar.

    Returns:
        Net driving pressure, bar (may be negative).
    """

    _require(feed_osmotic_bar >= 0, "feed osmotic pressure must be non-negative")
    _require(permeate_osmotic_bar >= 0, "permeate osmotic pressure must be non-negative")
    hydraulic = feed_pressure_bar - permeate_pressure_bar
    osmotic = feed_osmotic_bar - permeate_osmotic_bar
    return hydraulic - osmotic


def temperature_correction_factor(temperature_c: float) -> float:
    """Membrane temperature correction factor (TCF), dimensionless.

    Basis: Arrhenius-type water-permeability model
    ``TCF = exp(k * (1/T - 1/T_ref))`` with ``k = 2700 K`` and
    ``T_ref = 298.15 K`` (25 C). Because permeability falls with temperature,
    colder water gives ``TCF > 1`` (measured flow is normalised *up* to the 25 C
    reference) and warmer water gives ``TCF < 1``.

    Args:
        temperature_c: Water temperature, degrees Celsius.

    Returns:
        Temperature correction factor, dimensionless (=1 at 25 C).
    """

    _require(temperature_c > -KELVIN_OFFSET, "temperature must be above absolute zero")
    temperature_k = temperature_c + KELVIN_OFFSET
    return math.exp(_TCF_ACTIVATION_K * (1.0 / temperature_k - 1.0 / _REF_TEMPERATURE_K))


def normalized_permeate_flow(
    permeate_flow_m3h: float,
    ndp_bar: float,
    temperature_c: float,
    ref_ndp_bar: float,
) -> float:
    """Permeate flow normalised to reference NDP and 25 C, m^3/h.

    Basis: RO normalisation ``Q_norm = Q * (NDP_ref / NDP) * TCF``. Removes the
    influence of operating pressure and temperature so that a declining
    normalised flow reveals true membrane fouling.

    Args:
        permeate_flow_m3h: Measured permeate flow, m^3/h.
        ndp_bar: Current net driving pressure, bar.
        temperature_c: Water temperature, degrees Celsius.
        ref_ndp_bar: Reference net driving pressure, bar.

    Returns:
        Normalised permeate flow, m^3/h.
    """

    _require(ndp_bar > 0, "net driving pressure must be positive")
    _require(ref_ndp_bar > 0, "reference net driving pressure must be positive")
    _require(permeate_flow_m3h >= 0, "permeate flow must be non-negative")
    tcf = temperature_correction_factor(temperature_c)
    return permeate_flow_m3h * (ref_ndp_bar / ndp_bar) * tcf


# --------------------------------------------------------------------------- #
# Mass / energy balances.
# --------------------------------------------------------------------------- #
def mass_balance_error(
    feed_flow_m3h: float,
    permeate_flow_m3h: float,
    brine_flow_m3h: float,
) -> float:
    """Relative volumetric mass-balance closure error, dimensionless fraction.

    Basis: ``|Q_feed - (Q_permeate + Q_brine)| / Q_feed``. Ideally 0; a nonzero
    value flags instrumentation drift or leaks. Reported as a fraction of feed.

    Args:
        feed_flow_m3h: Feed flow, m^3/h.
        permeate_flow_m3h: Permeate flow, m^3/h.
        brine_flow_m3h: Brine (reject) flow, m^3/h.

    Returns:
        Relative mass-balance error, dimensionless (>= 0).
    """

    _require(feed_flow_m3h > 0, "feed flow must be positive")
    _require(permeate_flow_m3h >= 0, "permeate flow must be non-negative")
    _require(brine_flow_m3h >= 0, "brine flow must be non-negative")
    return abs(feed_flow_m3h - (permeate_flow_m3h + brine_flow_m3h)) / feed_flow_m3h


def energy_recovery_efficiency(
    hp_feed_out_bar: float,
    lp_feed_in_bar: float,
    hp_brine_in_bar: float,
    brine_out_bar: float,
) -> float:
    """Pressure-transfer efficiency of an isobaric ERD, fraction in [0, 1].

    Basis: for an isobaric energy-recovery device (e.g. rotary pressure
    exchanger) the pressure-transfer efficiency is the pressure gained by the
    low-pressure feed divided by the pressure given up by the high-pressure
    brine:
    ``eta = (P_feed_out - P_feed_in) / (P_brine_in - P_brine_out)``.
    Clamped to [0, 1]; the brine must arrive at higher pressure than it leaves.

    Args:
        hp_feed_out_bar: Boosted feed pressure leaving the ERD, bar.
        lp_feed_in_bar: Low-pressure feed pressure entering the ERD, bar.
        hp_brine_in_bar: High-pressure brine pressure entering the ERD, bar.
        brine_out_bar: Low-pressure brine pressure leaving the ERD, bar.

    Returns:
        Pressure-transfer efficiency in [0, 1].
    """

    _require(
        hp_brine_in_bar > brine_out_bar,
        "brine inlet pressure must exceed brine outlet pressure",
    )
    _require(
        hp_feed_out_bar >= lp_feed_in_bar,
        "feed outlet pressure must be >= feed inlet pressure",
    )
    gained = hp_feed_out_bar - lp_feed_in_bar
    available = hp_brine_in_bar - brine_out_bar
    return _clamp(gained / available, 0.0, 1.0)


def brine_salt_load_kg_h(brine_flow_m3h: float, brine_tds_mg_l: float) -> float:
    """Salt mass flow carried by the brine stream, kg/h.

    Basis: ``load = Q[m^3/h] * TDS[mg/L] * 1000 L/m^3 / 1e6 mg/kg`` which reduces
    to ``Q * TDS / 1000``. Used for discharge-permitting and outfall load checks.

    Args:
        brine_flow_m3h: Brine flow, m^3/h.
        brine_tds_mg_l: Brine total dissolved solids, mg/L.

    Returns:
        Salt load, kg/h.
    """

    _require(brine_flow_m3h >= 0, "brine flow must be non-negative")
    _require(brine_tds_mg_l >= 0, "brine TDS must be non-negative")
    return brine_flow_m3h * brine_tds_mg_l / 1000.0


def contaminant_removal_pct(feed_conc: float, product_conc: float) -> float:
    """Contaminant removal, percent.

    Basis: ``removal% = (1 - C_product / C_feed) * 100``. Works for any
    consistent concentration unit (mg/L, ug/L, ...) as long as feed and product
    share it.

    Args:
        feed_conc: Feed-side contaminant concentration, any consistent unit.
        product_conc: Product-side contaminant concentration, same unit.

    Returns:
        Removal, percent (can be negative if product is more concentrated).
    """

    _require(feed_conc > 0, "feed concentration must be positive")
    _require(product_conc >= 0, "product concentration must be non-negative")
    return (1.0 - product_conc / feed_conc) * 100.0


# --------------------------------------------------------------------------- #
# Registry.
# --------------------------------------------------------------------------- #
def calc_registry() -> list[dict[str, Any]]:
    """Machine-readable catalogue of the calculation library.

    Returns a list of records, one per public calculation, describing its
    stable ``id``, the ``units`` of its output, and the physical ``domain`` it
    belongs to. Downstream layers use this to discover which validated physics
    are available instead of hard-coding formulas.
    """

    return [
        {"id": "pump_head_m", "units": "m", "domain": "pump_hydraulics"},
        {"id": "hydraulic_power_kw", "units": "kW", "domain": "pump_hydraulics"},
        {"id": "pump_efficiency", "units": "fraction[0,1]", "domain": "pump_hydraulics"},
        {
            "id": "wire_to_water_efficiency",
            "units": "fraction[0,1]",
            "domain": "pump_hydraulics",
        },
        {"id": "specific_energy_kwh_m3", "units": "kWh/m3", "domain": "energy"},
        {"id": "npsh_margin_m", "units": "m", "domain": "cavitation"},
        {"id": "cavitation_index", "units": "fraction[0,1]", "domain": "cavitation"},
        {"id": "bep_distance", "units": "fraction", "domain": "pump_hydraulics"},
        {"id": "recovery", "units": "fraction[0,1]", "domain": "membrane"},
        {"id": "concentration_factor", "units": "dimensionless", "domain": "membrane"},
        {"id": "salt_rejection", "units": "fraction[0,1]", "domain": "membrane"},
        {"id": "salt_passage", "units": "fraction[0,1]", "domain": "membrane"},
        {"id": "osmotic_pressure_bar", "units": "bar", "domain": "membrane"},
        {"id": "net_driving_pressure_bar", "units": "bar", "domain": "membrane"},
        {
            "id": "temperature_correction_factor",
            "units": "dimensionless",
            "domain": "membrane",
        },
        {"id": "normalized_permeate_flow", "units": "m3/h", "domain": "membrane"},
        {"id": "mass_balance_error", "units": "fraction", "domain": "mass_balance"},
        {
            "id": "energy_recovery_efficiency",
            "units": "fraction[0,1]",
            "domain": "energy",
        },
        {"id": "brine_salt_load_kg_h", "units": "kg/h", "domain": "mass_balance"},
        {"id": "contaminant_removal_pct", "units": "percent", "domain": "water_quality"},
    ]
