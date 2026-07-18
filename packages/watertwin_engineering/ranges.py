"""Engineering plausibility ranges for imported equipment/tag/lab specifications.

The templated spreadsheet importer (``services/watertwin-ingest``) validates every
numeric field it ingests against a physically plausible range so a fat-fingered
value -- a pump with a negative NPSHr, an efficiency above ``1.0`` or a rated head
of ``10,000 m`` -- is surfaced as a validation error in the review diff rather than
being silently imported.

Those ranges are *engineering knowledge*, so they live here in the single
canonical engineering package alongside the rest of the deterministic physics --
never hardcoded inside the parser. Each :class:`SpecRange` is a pure, declarative
bound with an explicit unit; :meth:`SpecRange.error_for` returns a human-readable
message that always names the specific range it violated, so the message can be
shown verbatim in the importer diff.

Nothing here performs I/O or touches any control path; these are declarative
reference bounds only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "SPECIFICATION_RANGES",
    "SpecRange",
    "specification_range",
    "specification_range_keys",
]


@dataclass(frozen=True)
class SpecRange:
    """A closed/open plausibility interval for a single numeric spec field.

    The bound is ``minimum <op> value <op> maximum`` where each side is inclusive
    (``<=``/``>=``) when the corresponding ``inclusive_*`` flag is set and
    exclusive (``<``/``>``) otherwise. ``minimum``/``maximum`` may be ``None`` for
    an unbounded side.
    """

    key: str
    unit: str
    minimum: float | None = None
    maximum: float | None = None
    inclusive_min: bool = True
    inclusive_max: bool = True
    description: str = ""

    def describe(self) -> str:
        """Return a compact human-readable form of the allowed range.

        Examples: ``"0 < value <= 1 (fraction)"`` or ``"value >= 0 (m)"``.
        """
        unit = f" ({self.unit})" if self.unit else ""
        if self.minimum is None and self.maximum is None:
            return f"any finite value{unit}"
        if self.minimum is not None and self.maximum is not None:
            lo = "<=" if self.inclusive_min else "<"
            hi = "<=" if self.inclusive_max else "<"
            return f"{_fmt(self.minimum)} {lo} value {hi} {_fmt(self.maximum)}{unit}"
        if self.minimum is not None:
            op = ">=" if self.inclusive_min else ">"
            return f"value {op} {_fmt(self.minimum)}{unit}"
        op = "<=" if self.inclusive_max else "<"
        return f"value {op} {_fmt(self.maximum)}{unit}"

    def contains(self, value: float) -> bool:
        """Return ``True`` when ``value`` is finite and within the range."""
        if not math.isfinite(value):
            return False
        if self.minimum is not None:
            if self.inclusive_min:
                if value < self.minimum:
                    return False
            elif value <= self.minimum:
                return False
        if self.maximum is not None:
            if self.inclusive_max:
                if value > self.maximum:
                    return False
            elif value >= self.maximum:
                return False
        return True

    def error_for(self, value: float) -> str | None:
        """Return an error message if ``value`` is out of range, else ``None``.

        The message always includes :meth:`describe` so the caller can surface the
        specific violated range directly in the review diff.
        """
        if not math.isfinite(value):
            return f"{self.key} value {value!r} is not a finite number; allowed {self.describe()}"
        if self.contains(value):
            return None
        return f"{self.key} value {_fmt(value)} out of range; allowed {self.describe()}"


def _fmt(value: float) -> str:
    """Render a bound without a trailing ``.0`` for whole numbers."""
    if value == int(value):
        return str(int(value))
    return repr(value)


#: Canonical plausibility ranges, keyed by ``<domain>.<field>``. These are broad
#: engineering sanity bounds (not tuning parameters): they exist to catch data-
#: entry mistakes, so they are generous enough to admit any real-world unit while
#: still rejecting physically impossible values.
SPECIFICATION_RANGES: dict[str, SpecRange] = {
    # --- Equipment nameplate / rated data ---------------------------------
    "equipment.rated_flow_m3h": SpecRange(
        key="rated_flow_m3h", unit="m3/h", minimum=0.0, maximum=100_000.0,
        inclusive_min=False, description="Rated volumetric flow.",
    ),
    "equipment.rated_head_m": SpecRange(
        key="rated_head_m", unit="m", minimum=0.0, maximum=1_000.0,
        inclusive_min=False, description="Rated pump head (a 10,000 m head is a typo).",
    ),
    "equipment.rated_power_kw": SpecRange(
        key="rated_power_kw", unit="kW", minimum=0.0, maximum=50_000.0,
        inclusive_min=False, description="Rated shaft/motor power.",
    ),
    "equipment.speed_rpm": SpecRange(
        key="speed_rpm", unit="rpm", minimum=0.0, maximum=30_000.0,
        inclusive_min=False, description="Rated rotational speed.",
    ),
    "equipment.efficiency_fraction": SpecRange(
        key="efficiency_fraction", unit="fraction", minimum=0.0, maximum=1.0,
        inclusive_min=False, description="Best-efficiency-point efficiency as a fraction (0-1).",
    ),
    "equipment.npshr_m": SpecRange(
        key="npshr_m", unit="m", minimum=0.0, maximum=100.0,
        description="Net positive suction head required (never negative).",
    ),
    # --- Tag mapping scaling ---------------------------------------------
    "tag_mapping.scale": SpecRange(
        key="scale", unit="dimensionless", minimum=-1_000_000.0, maximum=1_000_000.0,
        description="Linear scale factor (canonical = raw * scale + offset).",
    ),
    "tag_mapping.offset": SpecRange(
        key="offset", unit="engineering units", minimum=-1.0e9, maximum=1.0e9,
        description="Linear offset (canonical = raw * scale + offset).",
    ),
    "tag_mapping.deadband": SpecRange(
        key="deadband", unit="engineering units", minimum=0.0, maximum=1.0e9,
        description="Change-of-value deadband (never negative).",
    ),
    # --- Lab method detection limits -------------------------------------
    "lab.lod": SpecRange(
        key="lod", unit="method unit", minimum=0.0, maximum=1.0e9,
        description="Limit of detection (never negative).",
    ),
    "lab.loq": SpecRange(
        key="loq", unit="method unit", minimum=0.0, maximum=1.0e9,
        description="Limit of quantitation (never negative).",
    ),
}


def specification_range_keys() -> list[str]:
    """Return the sorted list of known specification-range keys."""
    return sorted(SPECIFICATION_RANGES)


def specification_range(key: str) -> SpecRange:
    """Return the :class:`SpecRange` registered under ``key`` (KeyError if absent)."""
    return SPECIFICATION_RANGES[key]
