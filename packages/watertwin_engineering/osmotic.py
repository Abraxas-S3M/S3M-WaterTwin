"""Osmotic-pressure estimates for saline streams.

These are idealised, deterministic estimates suitable for advisory, preliminary
analytics. The van't Hoff model tends to slightly overestimate the osmotic
pressure of real seawater; results are engineering approximations, not
laboratory-validated measurements.
"""

from __future__ import annotations

from watertwin_engineering.constants import (
    GAS_CONSTANT_J_PER_MOL_K,
    KELVIN_OFFSET,
    NACL_MOLAR_MASS_G_PER_MOL,
    NACL_VANT_HOFF_FACTOR,
    PASCAL_PER_BAR,
)


def osmotic_pressure_bar(
    tds_mg_per_l: float,
    temperature_c: float = 25.0,
    *,
    vant_hoff_factor: float = NACL_VANT_HOFF_FACTOR,
    molar_mass_g_per_mol: float = NACL_MOLAR_MASS_G_PER_MOL,
) -> float:
    """Estimate osmotic pressure from total dissolved solids via van't Hoff.

    The van't Hoff relation is ``pi = i * c * R * T`` where ``c`` is the molar
    concentration of dissolved species. Dissolved solids are modelled as NaCl.

    Args:
        tds_mg_per_l: Total dissolved solids, mg/L (>= 0).
        temperature_c: Stream temperature, degrees Celsius (> -273.15).
        vant_hoff_factor: Dissociation factor ``i`` (> 0). Defaults to NaCl (2).
        molar_mass_g_per_mol: Molar mass of the modelled salt, g/mol (> 0).

    Returns:
        Osmotic pressure in bar (>= 0).

    Raises:
        ValueError: If any argument is outside its valid range.
    """

    if tds_mg_per_l < 0:
        raise ValueError("tds_mg_per_l must be non-negative.")
    if temperature_c <= -KELVIN_OFFSET:
        raise ValueError("temperature_c must be above absolute zero.")
    if vant_hoff_factor <= 0:
        raise ValueError("vant_hoff_factor must be positive.")
    if molar_mass_g_per_mol <= 0:
        raise ValueError("molar_mass_g_per_mol must be positive.")

    temperature_k = temperature_c + KELVIN_OFFSET
    # mg/L -> g/L -> mol/L -> mol/m^3
    concentration_mol_per_l = (tds_mg_per_l / 1000.0) / molar_mass_g_per_mol
    concentration_mol_per_m3 = concentration_mol_per_l * 1000.0

    pressure_pa = (
        vant_hoff_factor * concentration_mol_per_m3 * GAS_CONSTANT_J_PER_MOL_K * temperature_k
    )
    return pressure_pa / PASCAL_PER_BAR


def seawater_osmotic_pressure_bar(tds_mg_per_l: float, temperature_c: float) -> float:
    """Estimate seawater osmotic pressure using NaCl-equivalent van't Hoff.

    Convenience wrapper around :func:`osmotic_pressure_bar` with the NaCl
    defaults, provided for readability at call sites dealing with seawater.
    """

    return osmotic_pressure_bar(tds_mg_per_l, temperature_c)
