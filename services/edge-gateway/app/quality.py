"""Data-quality validation with quality flags.

Each collected reading is scored against four checks and tagged with a single
canonical quality flag (plus the full set of triggered reasons):

* **range**   -- value outside the metric's configured operating range;
* **staleness** -- the reading's timestamp is older than a freshness limit;
* **frozen-signal** -- the value has not changed for N consecutive samples;
* **deadband** -- the value changed by less than a configured deadband (an
  insignificant / not-meaningful change).

Flags are advisory metadata carried on the canonical reading's ``quality``
field; the gateway forwards every reading with its flag so downstream consumers
(and operators) can decide how to treat it. Nothing here mutates a control
system.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# Canonical quality flags (single primary flag per reading).
GOOD = "good"
NON_FINITE = "non_finite"
OUT_OF_RANGE = "out_of_range"
STALE = "stale"
FROZEN = "frozen"
DEADBAND = "deadband"

#: Sensible default operating ranges (metric -> (min, max)) for the reference RO
#: train's canonical signals. Overridable via the gateway config; a metric with
#: no configured range simply skips the range check.
DEFAULT_RANGES: dict[str, tuple[float, float]] = {
    "winding_temp_c": (0.0, 200.0),
    "bearing_temp_c": (0.0, 150.0),
    "vibration_mm_s": (0.0, 50.0),
    "dp_bar": (0.0, 10.0),
    "efficiency_drift_pct": (-50.0, 50.0),
    "transfer_efficiency_pct": (0.0, 100.0),
    "seal_leakage_ml_min": (0.0, 1000.0),
}


@dataclass
class QualityResult:
    """The quality assessment of a single reading."""

    flag: str
    reasons: list[str] = field(default_factory=list)
    #: ``False`` only when the value itself is unusable (non-finite / out of
    #: range). Stale / frozen / deadband readings stay usable but flagged.
    valid: bool = True


@dataclass
class _SignalState:
    last_value: Optional[float] = None
    repeat_count: int = 0  # consecutive identical samples (including the last)


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        value = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class QualityMonitor:
    """Stateful data-quality evaluator (tracks per-signal history for freeze)."""

    def __init__(
        self,
        *,
        ranges: Optional[dict[str, tuple[float, float]]] = None,
        staleness_limit_s: float = 60.0,
        frozen_limit: int = 10,
        deadband: float = 0.0,
    ) -> None:
        self.ranges = DEFAULT_RANGES if ranges is None else ranges
        self.staleness_limit_s = staleness_limit_s
        self.frozen_limit = max(1, frozen_limit)
        self.deadband = max(0.0, deadband)
        self._state: dict[tuple[str, str], _SignalState] = {}

    def evaluate(
        self,
        asset_id: str,
        metric: str,
        value: float,
        timestamp: Optional[str],
        *,
        now: Optional[datetime] = None,
    ) -> QualityResult:
        """Assess one reading, updating per-signal history, and return its flag."""
        reasons: list[str] = []

        if value is None or not math.isfinite(value):
            # Do not update freeze history on a non-finite value.
            return QualityResult(flag=NON_FINITE, reasons=[NON_FINITE], valid=False)

        # --- range ---
        rng = self.ranges.get(metric)
        out_of_range = rng is not None and not (rng[0] <= value <= rng[1])
        if out_of_range:
            reasons.append(OUT_OF_RANGE)

        # --- staleness ---
        now = now or datetime.now(timezone.utc)
        parsed = _parse_ts(timestamp)
        if parsed is not None:
            age = (now - parsed).total_seconds()
            if age > self.staleness_limit_s:
                reasons.append(STALE)

        # --- frozen-signal + deadband (stateful) ---
        key = (asset_id, metric)
        state = self._state.get(key)
        if state is None:
            state = _SignalState()
            self._state[key] = state

        frozen = False
        deadband_hit = False
        if state.last_value is not None:
            delta = abs(value - state.last_value)
            if value == state.last_value:
                state.repeat_count += 1
            else:
                state.repeat_count = 1
                if self.deadband > 0.0 and delta <= self.deadband:
                    deadband_hit = True
            if state.repeat_count >= self.frozen_limit:
                frozen = True
        else:
            state.repeat_count = 1
        state.last_value = value

        if frozen:
            reasons.append(FROZEN)
        if deadband_hit:
            reasons.append(DEADBAND)

        # Primary flag by severity: unusable value first, then freshness /
        # freeze / deadband, else good.
        if out_of_range:
            return QualityResult(flag=OUT_OF_RANGE, reasons=reasons, valid=False)
        if STALE in reasons:
            return QualityResult(flag=STALE, reasons=reasons, valid=True)
        if frozen:
            return QualityResult(flag=FROZEN, reasons=reasons, valid=True)
        if deadband_hit:
            return QualityResult(flag=DEADBAND, reasons=reasons, valid=True)
        return QualityResult(flag=GOOD, reasons=[GOOD], valid=True)
