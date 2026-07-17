"""Deterministic water-quality calculations for seawater RO.

This module extends the single canonical physics engine
(:mod:`watertwin_engineering`) with the scaling-, fouling-, and boron-related
math used by the Water Quality Intelligence capability. Like the rest of the
package, every function here is pure and deterministic: it performs no I/O and,
given the same inputs, always returns the same outputs.

These are **advisory, preliminary** engineering estimates -- screening-grade
approximations for operator decision support, not laboratory-validated
predictions or guaranteed compliance figures. Ionic-strength (activity) and
temperature corrections are applied only as explicitly documented
approximations; where they are omitted the concentration is treated as the
activity, which over-predicts scaling risk slightly (a conservative bias).

Units are stated explicitly in every signature. Concentrations expressed
"as CaCO3" follow the usual water-chemistry convention for hardness/alkalinity.
"""

from __future__ import annotations

import math

# --- Reference constants (documented, not tuning parameters) ----------------

#: Molar masses, g/mol (CRC Handbook of Chemistry and Physics).
_MOLAR_MASS_G_PER_MOL: dict[str, float] = {
    "Ca": 40.078,
    "Ba": 137.327,
    "Sr": 87.62,
    "SO4": 96.06,
}

#: Solubility-product constants Ksp at 25 C, (mol/L)^2, for the sparingly
#: soluble sulfate scales. Sources (CRC Handbook; Snoeyink & Jenkins,
#: *Water Chemistry*, 1980):
#:   * CaSO4 (gypsum, CaSO4.2H2O): 3.14e-5  (pKsp ~= 4.5)
#:   * BaSO4 (barite):            1.08e-10  (pKsp ~= 9.97)
#:   * SrSO4 (celestite):         3.44e-7   (pKsp ~= 6.46)
_SULFATE_KSP_25C: dict[str, float] = {
    "CaSO4": 3.14e-5,
    "BaSO4": 1.08e-10,
    "SrSO4": 3.44e-7,
}

#: Cation paired with each sulfate salt.
_SULFATE_CATION: dict[str, str] = {
    "CaSO4": "Ca",
    "BaSO4": "Ba",
    "SrSO4": "Sr",
}

#: Boric-acid dissociation constant pKa at 25 C (~9.2). Boric acid (H3BO3) is a
#: weak acid; above the pKa the borate ion (B(OH)4-) dominates. Neutral boric
#: acid permeates RO membranes readily; the charged borate ion is well rejected.
_BORON_PKA_25C: float = 9.24

#: Mild temperature sensitivity of the boron pKa, per deg C (documented
#: approximation; pKa falls slightly as temperature rises).
_BORON_PKA_TEMP_COEFF_PER_C: float = 0.008

#: Base fractional rejections for the two boron species (preliminary defaults
#: for a seawater RO membrane). Tight SWRO membranes still reject the neutral
#: boric-acid species fairly well (~0.88); the charged borate ion is rejected
#: almost completely (~0.98). Rejection therefore rises with pH.
_BORON_REJECTION_BORIC: float = 0.88
_BORON_REJECTION_BORATE: float = 0.98

#: Amorphous-silica solubility model (as SiO2). Base solubility at 25 C and a
#: linear temperature slope are engineering approximations to the amorphous
#: silica solubility curve (~120 mg/L at 25 C, rising with temperature).
_SILICA_SOLUBILITY_25C_MG_L: float = 120.0
_SILICA_SOLUBILITY_SLOPE_MG_L_PER_C: float = 2.9

#: Salt-passage temperature coefficient used when normalising to a reference
#: temperature (documented approximation for the temperature dependence of the
#: salt-transport coefficient B). Per deg C.
_SALT_PASSAGE_TEMP_COEFF_PER_C: float = 0.03

#: Feed-channel differential-pressure vs flow exponent. Turbulent spacer-filled
#: channel dP scales roughly with flow^1.5 (documented approximation).
_DP_FLOW_EXPONENT: float = 1.5

#: Screening scale factors for the colloidal fouling index composite.
_SDI_MAX: float = 6.5  # SDI15 saturates near 6.67.
_TURBIDITY_SCALE_NTU: float = 5.0
_PARTICLE_SCALE_PER_ML: float = 5000.0

REFERENCE_TEMPERATURE_C: float = 25.0

__all__ = [
    "langelier_saturation_index",
    "sulfate_scaling_ratio",
    "silica_saturation_pct",
    "boron_rejection",
    "normalized_salt_passage",
    "normalized_differential_pressure",
    "colloidal_fouling_index",
]


def _require_positive(**named_values: float) -> None:
    """Raise ``ValueError`` if any provided value is not strictly positive."""
    for name, value in named_values.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive.")


def _require_non_negative(**named_values: float) -> None:
    """Raise ``ValueError`` if any provided value is negative."""
    for name, value in named_values.items():
        if value < 0:
            raise ValueError(f"{name} must be non-negative.")


def langelier_saturation_index(
    ph: float,
    tds_mg_l: float,
    calcium_mg_l_as_caco3: float,
    alkalinity_mg_l_as_caco3: float,
    temperature_c: float,
) -> float:
    """Langelier Saturation Index (LSI), dimensionless.

    ``LSI = pH - pHs`` where ``pHs`` is the pH at which the water is just
    saturated with calcium carbonate. A **positive** LSI indicates a CaCO3
    scaling (precipitating) tendency; a **negative** LSI indicates corrosive,
    under-saturated water.

    Basis (Langelier, 1936; standard form as given in AWWA references):

    ``pHs = (9.3 + A + B) - (C + D)`` with

    * ``A = (log10(TDS) - 1) / 10``
    * ``B = -13.12 * log10(T_K) + 34.55`` (``T_K`` = temperature in kelvin)
    * ``C = log10([Ca2+ as CaCO3]) - 0.4``
    * ``D = log10([alkalinity as CaCO3])``

    Args:
        ph: Measured pH (dimensionless, 0-14).
        tds_mg_l: Total dissolved solids, mg/L (> 0).
        calcium_mg_l_as_caco3: Calcium hardness as CaCO3, mg/L (> 0).
        alkalinity_mg_l_as_caco3: Total alkalinity as CaCO3, mg/L (> 0).
        temperature_c: Water temperature, deg C (> -273.15).

    Returns:
        The LSI value (``pH - pHs``).

    Raises:
        ValueError: If any concentration/TDS is not positive, pH is outside
            0-14, or temperature is at/below absolute zero.
    """
    if not 0.0 <= ph <= 14.0:
        raise ValueError("ph must be in the range [0, 14].")
    _require_positive(
        tds_mg_l=tds_mg_l,
        calcium_mg_l_as_caco3=calcium_mg_l_as_caco3,
        alkalinity_mg_l_as_caco3=alkalinity_mg_l_as_caco3,
    )
    if temperature_c <= -273.15:
        raise ValueError("temperature_c must be above absolute zero.")

    temperature_k = temperature_c + 273.15
    a = (math.log10(tds_mg_l) - 1.0) / 10.0
    b = -13.12 * math.log10(temperature_k) + 34.55
    c = math.log10(calcium_mg_l_as_caco3) - 0.4
    d = math.log10(alkalinity_mg_l_as_caco3)
    ph_s = (9.3 + a + b) - (c + d)
    return ph - ph_s


def sulfate_scaling_ratio(cation_mg_l: float, sulfate_mg_l: float, salt: str) -> float:
    """Saturation ratio (S&DSI-style) for a sparingly soluble sulfate scale.

    Computes ``S = ion_product / Ksp`` using molar concentrations and the
    standard 25 C solubility-product constants documented at module level. A
    ratio ``> 1`` indicates super-saturation (scaling risk); ``< 1`` indicates
    under-saturation.

    Ion product ``IP = [cation][SO4^2-]`` in ``(mol/L)^2``. Activity
    coefficients (ionic-strength correction) are treated as unity -- a
    documented approximation that slightly over-predicts risk (conservative).
    Temperature is likewise not corrected here; the 25 C Ksp is used directly.

    Ksp values (25 C, ``(mol/L)^2``):
        * CaSO4 (gypsum): 3.14e-5  (CRC; Snoeyink & Jenkins)
        * BaSO4 (barite): 1.08e-10 (CRC)
        * SrSO4 (celestite): 3.44e-7 (CRC)

    Args:
        cation_mg_l: Cation concentration (Ca2+, Ba2+ or Sr2+), mg/L (>= 0).
        sulfate_mg_l: Sulfate (SO4^2-) concentration, mg/L (>= 0).
        salt: One of ``"CaSO4"``, ``"BaSO4"``, ``"SrSO4"``.

    Returns:
        Dimensionless saturation ratio (>= 0).

    Raises:
        ValueError: If ``salt`` is unknown or a concentration is negative.
    """
    if salt not in _SULFATE_KSP_25C:
        raise ValueError(
            f"salt must be one of {sorted(_SULFATE_KSP_25C)}; got {salt!r}."
        )
    _require_non_negative(cation_mg_l=cation_mg_l, sulfate_mg_l=sulfate_mg_l)

    cation = _SULFATE_CATION[salt]
    cation_mol_l = (cation_mg_l / 1000.0) / _MOLAR_MASS_G_PER_MOL[cation]
    sulfate_mol_l = (sulfate_mg_l / 1000.0) / _MOLAR_MASS_G_PER_MOL["SO4"]
    ion_product = cation_mol_l * sulfate_mol_l
    return ion_product / _SULFATE_KSP_25C[salt]


def silica_saturation_pct(silica_mg_l: float, temperature_c: float, ph: float) -> float:
    """Amorphous-silica saturation as a percentage of solubility (screening).

    ``saturation_pct = 100 * C_silica / S(T, pH)`` where ``S`` is the amorphous
    silica solubility (as SiO2). Solubility rises with temperature and, above
    pH ~8, with pH (silica is more soluble as it ionises to silicate). Values
    ``>= 100 %`` indicate a silica scaling tendency.

    This is a **screening estimate** only: it uses a linear temperature model
    around a 25 C base solubility and a simple high-pH enhancement. It is not a
    substitute for a validated silica-scaling model.

    Basis: amorphous silica solubility ~120 mg/L (as SiO2) at 25 C, increasing
    roughly linearly with temperature; ionisation raises solubility above pH 8.

    Args:
        silica_mg_l: Reactive silica as SiO2, mg/L (>= 0).
        temperature_c: Water temperature, deg C (> -273.15).
        ph: Measured pH (0-14).

    Returns:
        Saturation percentage (>= 0), where 100 % is the solubility limit.

    Raises:
        ValueError: If silica is negative, pH is outside 0-14, or temperature
            is at/below absolute zero.
    """
    _require_non_negative(silica_mg_l=silica_mg_l)
    if not 0.0 <= ph <= 14.0:
        raise ValueError("ph must be in the range [0, 14].")
    if temperature_c <= -273.15:
        raise ValueError("temperature_c must be above absolute zero.")

    solubility = _SILICA_SOLUBILITY_25C_MG_L + _SILICA_SOLUBILITY_SLOPE_MG_L_PER_C * (
        temperature_c - REFERENCE_TEMPERATURE_C
    )
    solubility = max(solubility, 10.0)  # floor to keep the estimate well-posed
    ph_factor = 1.0 + 0.30 * max(0.0, ph - 8.0)
    solubility *= ph_factor
    return 100.0 * silica_mg_l / solubility


def boron_rejection(
    ph: float,
    temperature_c: float,
    membrane_age_factor: float = 1.0,
) -> float:
    """Fractional boron rejection from a pKa-based speciation model (preliminary).

    Boron in water is present as neutral boric acid (H3BO3) and the borate ion
    (B(OH)4-). The neutral species passes RO membranes readily (low rejection)
    while the charged borate ion is well rejected. The borate fraction follows
    the Henderson-Hasselbalch relation around the boric-acid ``pKa`` (~9.2), so
    **rejection rises with pH**:

    ``f_borate = 1 / (1 + 10^(pKa - pH))``
    ``rejection = R_boric * (1 - f_borate) + R_borate * f_borate``

    The result is scaled by ``membrane_age_factor`` (a value in (0, 1] where
    lower means an older/degraded membrane that passes more boron). The pKa is
    given a mild temperature dependence (documented approximation).

    This is a **preliminary** model for advisory screening, not a validated
    permeate-boron prediction.

    Args:
        ph: Feed pH (0-14).
        temperature_c: Water temperature, deg C (> -273.15).
        membrane_age_factor: Rejection de-rating for membrane age, (0, 1].

    Returns:
        Fractional boron rejection in [0, 1].

    Raises:
        ValueError: If pH is outside 0-14, temperature is at/below absolute
            zero, or ``membrane_age_factor`` is outside (0, 1].
    """
    if not 0.0 <= ph <= 14.0:
        raise ValueError("ph must be in the range [0, 14].")
    if temperature_c <= -273.15:
        raise ValueError("temperature_c must be above absolute zero.")
    if not 0.0 < membrane_age_factor <= 1.0:
        raise ValueError("membrane_age_factor must be in the range (0, 1].")

    pka = _BORON_PKA_25C - _BORON_PKA_TEMP_COEFF_PER_C * (
        temperature_c - REFERENCE_TEMPERATURE_C
    )
    f_borate = 1.0 / (1.0 + 10.0 ** (pka - ph))
    rejection = (
        _BORON_REJECTION_BORIC * (1.0 - f_borate) + _BORON_REJECTION_BORATE * f_borate
    )
    rejection *= membrane_age_factor
    return max(0.0, min(1.0, rejection))


def normalized_salt_passage(
    salt_passage: float,
    ndp_bar: float,
    temperature_c: float,
    ref_ndp_bar: float,
    ref_temperature_c: float = REFERENCE_TEMPERATURE_C,
) -> float:
    """Normalise observed salt passage to reference NDP and temperature.

    Observed salt passage ``SP = Cp/Cf`` depends on operating conditions: for a
    fixed salt-transport coefficient it scales inversely with water flux (hence
    with net driving pressure), and it rises with temperature. Normalising to
    reference conditions removes those operating effects so that a rising
    *normalised* salt passage reflects genuine membrane deterioration rather
    than a change in pressure or temperature (ASTM D4516 in spirit):

    ``SP_norm = SP * (NDP / NDP_ref) * exp(-k * (T - T_ref))``

    The temperature coefficient ``k`` (~0.03 /deg C) is a documented
    approximation for the temperature dependence of salt transport.

    Args:
        salt_passage: Observed salt passage fraction ``Cp/Cf`` (>= 0).
        ndp_bar: Actual net driving pressure, bar (> 0).
        temperature_c: Actual water temperature, deg C.
        ref_ndp_bar: Reference net driving pressure, bar (> 0).
        ref_temperature_c: Reference temperature, deg C (default 25).

    Returns:
        Normalised salt passage fraction (>= 0).

    Raises:
        ValueError: If ``salt_passage`` is negative or an NDP is not positive.
    """
    _require_non_negative(salt_passage=salt_passage)
    _require_positive(ndp_bar=ndp_bar, ref_ndp_bar=ref_ndp_bar)

    ndp_factor = ndp_bar / ref_ndp_bar
    temp_factor = math.exp(
        -_SALT_PASSAGE_TEMP_COEFF_PER_C * (temperature_c - ref_temperature_c)
    )
    return salt_passage * ndp_factor * temp_factor


def normalized_differential_pressure(
    dp_bar: float,
    flow_m3h: float,
    ref_flow_m3h: float,
) -> float:
    """Normalise vessel differential pressure to a reference feed flow.

    Feed-channel (spacer-filled) differential pressure scales with feed flow
    raised to an exponent of ~1.5 for turbulent flow. Normalising to a
    reference flow lets a rising *normalised* dP reveal fouling/plugging that is
    independent of the current throughput:

    ``dP_norm = dP * (Q_ref / Q)^n`` with ``n ~= 1.5`` (documented approximation).

    Args:
        dp_bar: Measured vessel/stage differential pressure, bar (>= 0).
        flow_m3h: Actual feed flow, m3/h (> 0).
        ref_flow_m3h: Reference feed flow, m3/h (> 0).

    Returns:
        Normalised differential pressure, bar (>= 0).

    Raises:
        ValueError: If ``dp_bar`` is negative or a flow is not positive.
    """
    _require_non_negative(dp_bar=dp_bar)
    _require_positive(flow_m3h=flow_m3h, ref_flow_m3h=ref_flow_m3h)
    return dp_bar * (ref_flow_m3h / flow_m3h) ** _DP_FLOW_EXPONENT


def colloidal_fouling_index(
    sdi: float,
    turbidity_ntu: float,
    particle_count: float,
) -> float:
    """Composite colloidal fouling index in [0, 1] (screening).

    Combines three colloidal-fouling indicators onto a common 0-1 scale and
    returns a weighted blend. Higher values indicate a greater colloidal
    fouling propensity for downstream RO membranes.

    * SDI (Silt Density Index, SDI15) saturates near 6.67; scaled by 6.5.
    * Turbidity (NTU) scaled by 5 NTU (RO feed target is well below 1 NTU).
    * Particle count (per mL) scaled by 5000 /mL.

    Weights (SDI 0.5, turbidity 0.3, particle count 0.2) reflect SDI's status
    as the primary RO fouling screen. This is a screening composite, not a
    validated fouling-rate prediction.

    Args:
        sdi: Silt Density Index (SDI15), dimensionless (>= 0).
        turbidity_ntu: Turbidity, NTU (>= 0).
        particle_count: Particle count, particles per mL (>= 0).

    Returns:
        Composite fouling index in [0, 1].

    Raises:
        ValueError: If any input is negative.
    """
    _require_non_negative(
        sdi=sdi, turbidity_ntu=turbidity_ntu, particle_count=particle_count
    )

    sdi_norm = min(1.0, sdi / _SDI_MAX)
    turb_norm = min(1.0, turbidity_ntu / _TURBIDITY_SCALE_NTU)
    part_norm = min(1.0, particle_count / _PARTICLE_SCALE_PER_ML)
    composite = 0.5 * sdi_norm + 0.3 * turb_norm + 0.2 * part_norm
    return max(0.0, min(1.0, composite))
