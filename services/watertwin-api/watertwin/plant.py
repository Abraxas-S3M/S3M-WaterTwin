"""A deterministic synthetic water-treatment plant.

The :class:`SyntheticPlant` owns a catalog of assets and generates telemetry on
every ``tick``. It is fully deterministic given a seed so that resets and tests
are reproducible. Scenarios let us drive the plant into interesting states
(notably ``degrade``) to exercise analytics and recommendations.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .models import Asset, TelemetryReading

SCENARIOS = ("normal", "degrade", "leak", "recovery")


@dataclass(frozen=True)
class MetricSpec:
    """Describes how one metric behaves and how it should be judged."""

    name: str
    nominal: float
    noise: float
    warn: float
    crit: float
    unit: str
    higher_is_worse: bool = True
    degradable: bool = False


@dataclass
class AssetDef:
    asset: Asset
    metrics: list[MetricSpec] = field(default_factory=list)


def _pump(id_: str, name: str, location: str, cap: float, year: int) -> AssetDef:
    asset = Asset(
        id=id_,
        name=name,
        asset_type="pump",
        location=location,
        rated_capacity=cap,
        unit="m3/h",
        installed_year=year,
    )
    metrics = [
        MetricSpec("flow_m3h", cap * 0.9, cap * 0.02, cap * 0.7, cap * 0.5, "m3/h",
                   higher_is_worse=False),
        MetricSpec("discharge_pressure_bar", 8.0, 0.15, 11.0, 13.0, "bar"),
        MetricSpec("power_kw", cap * 0.12, cap * 0.004, cap * 0.16, cap * 0.2, "kW"),
        MetricSpec("vibration_mm_s", 2.0, 0.15, 4.5, 7.1, "mm/s", degradable=True),
        MetricSpec("bearing_temp_c", 55.0, 1.0, 80.0, 95.0, "C", degradable=True),
    ]
    return AssetDef(asset, metrics)


def _membrane(id_: str, name: str, location: str, cap: float, year: int) -> AssetDef:
    asset = Asset(
        id=id_,
        name=name,
        asset_type="membrane",
        location=location,
        rated_capacity=cap,
        unit="m3/h",
        installed_year=year,
    )
    metrics = [
        MetricSpec("permeate_flow_m3h", cap * 0.85, cap * 0.02, cap * 0.6, cap * 0.45,
                   "m3/h", higher_is_worse=False),
        MetricSpec("feed_pressure_bar", 55.0, 0.5, 68.0, 75.0, "bar", degradable=True),
        MetricSpec("differential_pressure_bar", 1.2, 0.05, 2.2, 3.0, "bar",
                   degradable=True),
        MetricSpec("salt_rejection_pct", 99.4, 0.05, 98.0, 96.5, "%",
                   higher_is_worse=False, degradable=True),
    ]
    return AssetDef(asset, metrics)


def _tank(id_: str, name: str, location: str, cap: float, year: int) -> AssetDef:
    asset = Asset(
        id=id_,
        name=name,
        asset_type="tank",
        location=location,
        rated_capacity=cap,
        unit="m3",
        installed_year=year,
    )
    metrics = [
        MetricSpec("level_pct", 65.0, 3.0, 90.0, 97.0, "%"),
        MetricSpec("volume_m3", cap * 0.65, cap * 0.03, cap * 0.9, cap * 0.97, "m3"),
    ]
    return AssetDef(asset, metrics)


def _filter(id_: str, name: str, location: str, cap: float, year: int) -> AssetDef:
    asset = Asset(
        id=id_,
        name=name,
        asset_type="filter",
        location=location,
        rated_capacity=cap,
        unit="m3/h",
        installed_year=year,
    )
    metrics = [
        MetricSpec("flow_m3h", cap * 0.9, cap * 0.02, cap * 0.7, cap * 0.5, "m3/h",
                   higher_is_worse=False),
        MetricSpec("differential_pressure_bar", 0.4, 0.03, 1.0, 1.4, "bar",
                   degradable=True),
        MetricSpec("turbidity_ntu", 0.15, 0.02, 0.5, 1.0, "NTU", degradable=True),
    ]
    return AssetDef(asset, metrics)


def _blower(id_: str, name: str, location: str, cap: float, year: int) -> AssetDef:
    asset = Asset(
        id=id_,
        name=name,
        asset_type="blower",
        location=location,
        rated_capacity=cap,
        unit="Nm3/h",
        installed_year=year,
    )
    metrics = [
        MetricSpec("airflow_nm3h", cap * 0.9, cap * 0.02, cap * 0.7, cap * 0.5,
                   "Nm3/h", higher_is_worse=False),
        MetricSpec("power_kw", cap * 0.02, cap * 0.001, cap * 0.03, cap * 0.04, "kW"),
        MetricSpec("vibration_mm_s", 2.5, 0.2, 5.0, 7.5, "mm/s", degradable=True),
    ]
    return AssetDef(asset, metrics)


def _valve(id_: str, name: str, location: str, cap: float, year: int) -> AssetDef:
    asset = Asset(
        id=id_,
        name=name,
        asset_type="valve",
        location=location,
        rated_capacity=cap,
        unit="m3/h",
        installed_year=year,
    )
    metrics = [
        MetricSpec("position_pct", 60.0, 1.0, 98.0, 100.0, "%"),
        MetricSpec("flow_m3h", cap * 0.6, cap * 0.02, cap * 0.4, cap * 0.25, "m3/h",
                   higher_is_worse=False),
    ]
    return AssetDef(asset, metrics)


def _analyzer(id_: str, name: str, location: str, year: int) -> AssetDef:
    asset = Asset(
        id=id_,
        name=name,
        asset_type="analyzer",
        location=location,
        rated_capacity=0.0,
        unit="n/a",
        installed_year=year,
    )
    metrics = [
        MetricSpec("turbidity_ntu", 0.12, 0.02, 0.5, 1.0, "NTU", degradable=True),
        MetricSpec("chlorine_mg_l", 0.8, 0.05, 0.2, 0.1, "mg/L", higher_is_worse=False),
        MetricSpec("ph", 7.4, 0.05, 8.5, 9.0, "pH"),
    ]
    return AssetDef(asset, metrics)


def build_catalog() -> list[AssetDef]:
    """Return the fixed catalog of plant assets (16 assets)."""

    return [
        _pump("INTK-001", "Raw Water Intake Pump", "Intake", 1200.0, 2016),
        _pump("HPP-001", "High Pressure Pump A", "RO Hall", 900.0, 2018),
        _pump("HPP-002", "High Pressure Pump B", "RO Hall", 900.0, 2018),
        _membrane("RO-TRAIN-001", "RO Membrane Train 1", "RO Hall", 750.0, 2018),
        _membrane("RO-TRAIN-002", "RO Membrane Train 2", "RO Hall", 750.0, 2019),
        _pump("DOS-CL2-001", "Chlorine Dosing Pump", "Chemical Bay", 5.0, 2020),
        _pump("DOS-ASC-001", "Antiscalant Dosing Pump", "Chemical Bay", 3.0, 2020),
        _filter("FILT-001", "Multimedia Filter 1", "Pretreatment", 1100.0, 2016),
        _filter("FILT-002", "Multimedia Filter 2", "Pretreatment", 1100.0, 2016),
        _tank("TANK-CLR-001", "Clearwell Storage Tank", "Post-treatment", 8000.0, 2015),
        _tank("TANK-RAW-001", "Raw Water Balancing Tank", "Intake", 5000.0, 2015),
        _blower("BLWR-001", "Aeration Blower", "Pretreatment", 4000.0, 2017),
        _pump("DIST-PMP-001", "Distribution Pump A", "Distribution", 1000.0, 2019),
        _pump("DIST-PMP-002", "Distribution Pump B", "Distribution", 1000.0, 2019),
        _valve("VLV-INLET-001", "Inlet Control Valve", "Intake", 1200.0, 2016),
        _analyzer("AN-TURB-001", "Product Water Quality Analyzer", "Post-treatment", 2021),
    ]


class SyntheticPlant:
    """Deterministic generator of plant telemetry."""

    def __init__(self, seed: int = 42, scenario: str = "normal") -> None:
        self._seed = seed
        self._scenario = scenario if scenario in SCENARIOS else "normal"
        self._catalog = build_catalog()
        self._specs = {d.asset.id: d for d in self._catalog}
        self._rng = random.Random(seed)
        self._tick_count = 0
        self._last_tick: datetime | None = None

    @property
    def scenario(self) -> str:
        return self._scenario

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def last_tick(self) -> datetime | None:
        return self._last_tick

    def assets(self) -> list[Asset]:
        return [d.asset for d in self._catalog]

    def get_asset(self, asset_id: str) -> Asset | None:
        d = self._specs.get(asset_id)
        return d.asset if d else None

    def metric_specs(self, asset_id: str) -> list[MetricSpec]:
        d = self._specs.get(asset_id)
        return list(d.metrics) if d else []

    def set_scenario(self, scenario: str) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario: {scenario!r}; choose one of {SCENARIOS}")
        self._scenario = scenario

    def reset(self, seed: int | None = None) -> None:
        """Deterministically reset the plant back to its initial state."""

        if seed is not None:
            self._seed = seed
        self._rng = random.Random(self._seed)
        self._tick_count = 0
        self._last_tick = None
        self._scenario = "normal"

    def _degrade_factor(self) -> float:
        """How far the plant has drifted from nominal under a stressing scenario."""

        if self._scenario == "normal":
            return 0.0
        if self._scenario == "recovery":
            # Ramp back down toward nominal.
            return max(0.0, 1.0 - self._tick_count * 0.05)
        # degrade / leak: ramp up, saturating around 1.0.
        return min(1.0, 1.0 - math.exp(-self._tick_count / 12.0))

    def tick(self, now: datetime | None = None) -> list[TelemetryReading]:
        """Advance the simulation one step and return readings for all assets."""

        self._tick_count += 1
        ts = now or datetime.now(UTC)
        self._last_tick = ts
        drift = self._degrade_factor()
        readings: list[TelemetryReading] = []

        for definition in self._catalog:
            metrics: dict[str, float] = {}
            for spec in definition.metrics:
                value = spec.nominal + self._rng.gauss(0.0, spec.noise)
                if spec.degradable and drift > 0.0:
                    span = (spec.crit - spec.nominal)
                    value += span * drift * (0.9 + 0.2 * self._rng.random())
                if self._scenario == "leak" and spec.name.endswith("pressure_bar"):
                    value -= abs(spec.nominal - spec.warn) * drift * 0.6
                metrics[spec.name] = round(value, 4)
            readings.append(
                TelemetryReading(asset_id=definition.asset.id, timestamp=ts, metrics=metrics)
            )
        return readings
