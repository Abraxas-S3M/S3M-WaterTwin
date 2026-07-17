"""Synthetic telemetry source (default).

Wraps the platform's existing synthetic plant telemetry -- the per-asset
telemetry declared on :data:`app.predictive_maintenance.ASSETS` -- and exposes
it through the :class:`TelemetrySource` interface as canonical
:class:`TelemetryReading` objects. It **reads** that existing synthetic data
unchanged; it does not alter how the synthetic plant behaves.
"""

from __future__ import annotations

from typing import Optional

from canonical_water_model import DataProvenance, TelemetryReading, now_iso

from .base import TelemetrySource

#: Engineering unit inferred from a metric-name suffix. Ordered longest-first so
#: e.g. ``winding_temp_c`` and ``vibration_mm_s`` resolve before generic ``_c``.
_UNIT_BY_SUFFIX: tuple[tuple[str, str], ...] = (
    ("_mm_s", "mm/s"),
    ("_ml_min", "mL/min"),
    ("_pct", "%"),
    ("_bar", "bar"),
    ("_c", "degC"),
)


def unit_for(metric: str) -> str:
    """Best-effort canonical unit for a synthetic telemetry metric name."""
    for suffix, unit in _UNIT_BY_SUFFIX:
        if metric.endswith(suffix):
            return unit
    return "dimensionless"


class SyntheticSource(TelemetrySource):
    """The default source: the existing synthetic plant telemetry, read-only."""

    kind = "synthetic"
    name = "synthetic"

    def __init__(self, assets: Optional[dict] = None) -> None:
        # Import lazily to avoid a hard import cycle with the API package and to
        # keep the (unchanged) synthetic plant the single source of truth.
        if assets is None:
            from ..predictive_maintenance import ASSETS

            assets = ASSETS
        self._assets = assets

    def read_latest(self) -> list[TelemetryReading]:
        ts = now_iso()
        readings: list[TelemetryReading] = []
        for spec in self._assets.values():
            for metric, value in spec.telemetry.items():
                readings.append(
                    TelemetryReading(
                        asset_id=spec.asset_id,
                        metric=metric,
                        value=float(value),
                        unit=unit_for(metric),
                        timestamp=ts,
                        provenance=DataProvenance.synthetic,
                    )
                )
        return readings

    def describe(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "asset_count": len(self._assets),
        }
