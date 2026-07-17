"""Physical constants and reference conditions for RO calculations.

Values are SI unless noted. These are textbook constants used by the
deterministic engineering math; they are not tuning parameters.
"""

from __future__ import annotations

#: Universal gas constant, J/(mol*K).
GAS_CONSTANT_J_PER_MOL_K: float = 8.314462618

#: Molar mass of sodium chloride, g/mol. Seawater osmotic estimates model the
#: dissolved solids as NaCl, which is the dominant salt in seawater.
NACL_MOLAR_MASS_G_PER_MOL: float = 58.44

#: Van't Hoff factor for fully dissociated NaCl (Na+ and Cl-).
NACL_VANT_HOFF_FACTOR: float = 2.0

#: Absolute-zero offset for Celsius <-> Kelvin conversion.
KELVIN_OFFSET: float = 273.15

#: Reference temperature used to normalise permeate flow, degrees Celsius.
#: 25 C is the industry-standard normalisation temperature for RO membranes.
REFERENCE_TEMPERATURE_C: float = 25.0

#: Membrane permeate-flow temperature-correction coefficient (per degree C).
#: Used in the exponential temperature-correction factor (TCF) approximation.
#: A value of ~0.03 corresponds to the commonly cited ~3%/C flux sensitivity.
TEMPERATURE_CORRECTION_COEFFICIENT_PER_C: float = 0.03

#: Pascals per bar.
PASCAL_PER_BAR: float = 1.0e5

#: Seconds per hour.
SECONDS_PER_HOUR: float = 3600.0
