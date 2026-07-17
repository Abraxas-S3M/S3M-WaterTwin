"""Synthetic telemetry source (default + graceful-fallback source).

Exposes a small synthetic plant through the :class:`TelemetrySource` interface
as canonical :class:`TelemetryReading` objects. It only ever **reads** data; it
never writes to any control system.

The set of synthetic assets is *pluggable* so this shared source can serve
different hosts without depending on any one service's internals:

* ``services/watertwin-api`` registers its existing synthetic plant
  (``app.predictive_maintenance.ASSETS``) via
  :func:`register_default_assets_provider`, so the API's synthetic telemetry is
  unchanged.
* ``services/edge-gateway`` (and any other importer) that does not register a
  provider falls back to the small :data:`BUILTIN_SYNTHETIC_ASSETS` bundled
  here, so the gateway can fall back to synthetic telemetry with no dependency
  on the API package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

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


@dataclass
class SyntheticAsset:
    """Minimal synthetic asset descriptor (``asset_id`` + ``telemetry`` map).

    Structurally compatible with the richer ``AssetSpec`` used by the API's
    predictive-maintenance layer -- :class:`SyntheticSource` only reads the
    ``asset_id`` and ``telemetry`` attributes.
    """

    asset_id: str
    telemetry: dict[str, float] = field(default_factory=dict)


#: A small, self-contained synthetic plant used when no host registers its own
#: assets (e.g. the edge-gateway's synthetic fallback). Deliberately mirrors the
#: reference RO train's canonical asset ids + metrics so downstream tag maps and
#: consumers see familiar signals.
BUILTIN_SYNTHETIC_ASSETS: dict[str, SyntheticAsset] = {
    "AST-HPP-01": SyntheticAsset(
        asset_id="AST-HPP-01",
        telemetry={
            "winding_temp_c": 150.0,
            "vibration_mm_s": 6.4,
            "bearing_temp_c": 92.0,
            "efficiency_drift_pct": 6.0,
        },
    ),
    "AST-CF-01": SyntheticAsset(
        asset_id="AST-CF-01",
        telemetry={"dp_bar": 0.57},
    ),
    "AST-ERD-01": SyntheticAsset(
        asset_id="AST-ERD-01",
        telemetry={"transfer_efficiency_pct": 96.0},
    ),
}

#: Optional provider that returns the default synthetic asset map. When unset the
#: :data:`BUILTIN_SYNTHETIC_ASSETS` are used. Registered as a *callable* (not the
#: dict itself) so a host can defer any heavy import until the source is built.
_default_assets_provider: Optional[Callable[[], dict]] = None


def register_default_assets_provider(provider: Optional[Callable[[], dict]]) -> None:
    """Register the provider used by ``SyntheticSource()`` when no assets are passed.

    ``services/watertwin-api`` uses this to keep its existing synthetic plant as
    the source of truth. Pass ``None`` to reset to the bundled default.
    """
    global _default_assets_provider
    _default_assets_provider = provider


class SyntheticSource(TelemetrySource):
    """The default source: a synthetic plant's telemetry, strictly read-only."""

    kind = "synthetic"
    name = "synthetic"

    def __init__(self, assets: Optional[dict] = None) -> None:
        if assets is None:
            if _default_assets_provider is not None:
                assets = _default_assets_provider()
            else:
                assets = BUILTIN_SYNTHETIC_ASSETS
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
