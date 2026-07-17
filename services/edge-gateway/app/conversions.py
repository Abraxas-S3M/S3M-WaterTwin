"""Unit conversion to canonical engineering units.

The tag map (reused from :mod:`ot_ingestion.tag_normalization`) already applies a
per-tag ``scale``/``offset`` when normalizing raw values. This module is a
secondary, unit-aware safety net that converts any remaining well-known
engineering units onto the platform's canonical units (e.g. degF -> degC,
kPa/psi/Pa -> bar) so downstream consumers only ever see canonical units.

Conversions are pure ``canonical = raw * factor + offset``; an unrecognized unit
passes through unchanged.
"""

from __future__ import annotations

#: source-unit (lower-cased) -> (canonical_unit, factor, offset).
_CONVERSIONS: dict[str, tuple[str, float, float]] = {
    # temperature
    "degf": ("degC", 5.0 / 9.0, -32.0 * 5.0 / 9.0),
    "f": ("degC", 5.0 / 9.0, -32.0 * 5.0 / 9.0),
    "fahrenheit": ("degC", 5.0 / 9.0, -32.0 * 5.0 / 9.0),
    "k": ("degC", 1.0, -273.15),
    "kelvin": ("degC", 1.0, -273.15),
    # pressure -> bar
    "kpa": ("bar", 0.01, 0.0),
    "pa": ("bar", 1e-5, 0.0),
    "mbar": ("bar", 0.001, 0.0),
    "psi": ("bar", 0.0689476, 0.0),
    # flow
    "l/min": ("m3/h", 0.06, 0.0),
    "lpm": ("m3/h", 0.06, 0.0),
}

#: Units already canonical (identity) -- listed for documentation/clarity.
_CANONICAL_UNITS = {"degc", "bar", "mm/s", "%", "m3/h", "ml/min", "dimensionless"}


def to_canonical(value: float, unit: str) -> tuple[float, str]:
    """Convert ``value`` in ``unit`` to canonical units.

    Returns ``(canonical_value, canonical_unit)``. Unknown or already-canonical
    units pass through unchanged.
    """
    key = (unit or "").strip().lower()
    conversion = _CONVERSIONS.get(key)
    if conversion is None:
        return value, unit
    canonical_unit, factor, offset = conversion
    return value * factor + offset, canonical_unit
