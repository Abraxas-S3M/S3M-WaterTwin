"""Synthetic telemetry generator for the seeded RO train.

``SyntheticPlant`` produces physics-shaped :class:`TelemetryReading` objects for
every asset in the plant.  It is:

* **Deterministic** -- a fixed ``seed`` plus :meth:`reset` reproduce identical
  sequences, which makes tests and demos repeatable.
* **Thread-safe** -- all mutating/reading operations are guarded by a lock so it
  can back a polling API or background sampler.
* **Scenario-driven** -- a fault scenario can be injected at runtime; its
  severity ramps smoothly from ``0`` to ``1`` over successive :meth:`tick` calls
  so faults develop gradually rather than as a step change.

All values are synthetic; readings carry ``provenance="synthetic"``.
"""

from __future__ import annotations

import random
import threading
from datetime import UTC, datetime, timedelta

from watertwin.models import Asset, AssetType, TelemetryReading
from watertwin.plant_seed import seed_assets

# Base timestamp for the deterministic virtual clock.
_EPOCH = datetime(2024, 1, 1, tzinfo=UTC)


class SyntheticPlant:
    """Generate synthetic, scenario-aware telemetry for the seeded RO train."""

    SCENARIOS: tuple[str, ...] = (
        "normal",
        "hpp_degradation",
        "membrane_fouling",
        "grid_outage",
    )

    def __init__(
        self,
        seed: int = 1337,
        ramp_steps: int = 12,
        step_seconds: float = 5.0,
        assets: list[Asset] | None = None,
    ) -> None:
        self._seed = seed
        self._ramp_steps = max(1, ramp_steps)
        self._step_seconds = step_seconds
        self._assets = list(assets) if assets is not None else seed_assets()
        self._lock = threading.RLock()

        self._rng = random.Random(seed)
        self._scenario = "normal"
        self._scenario_step = 0
        self._step = 0
        self._latest: dict[str, list[TelemetryReading]] = {}
        # Produce an initial baseline so latest() is populated before tick().
        self._latest = self._snapshot()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def scenario(self) -> str:
        """Name of the currently active scenario."""

        with self._lock:
            return self._scenario

    @property
    def severity(self) -> float:
        """Current scenario severity in ``[0, 1]`` (``0`` while normal)."""

        with self._lock:
            return self._severity()

    def set_scenario(self, name: str) -> None:
        """Activate a fault scenario and (re)start its severity ramp."""

        if name not in self.SCENARIOS:
            raise ValueError(f"unknown scenario {name!r}; expected one of {self.SCENARIOS}")
        with self._lock:
            self._scenario = name
            self._scenario_step = 0

    def reset(self) -> dict[str, list[TelemetryReading]]:
        """Restore the plant to a fresh, deterministic normal state."""

        with self._lock:
            self._rng = random.Random(self._seed)
            self._scenario = "normal"
            self._scenario_step = 0
            self._step = 0
            self._latest = self._snapshot()
            return self._copy_latest()

    def tick(self) -> dict[str, list[TelemetryReading]]:
        """Advance the simulation one step and return the new readings."""

        with self._lock:
            self._step += 1
            if self._scenario != "normal":
                self._scenario_step += 1
            self._latest = self._snapshot()
            return self._copy_latest()

    def latest(self) -> dict[str, list[TelemetryReading]]:
        """Return the most recent readings keyed by ``asset_id``."""

        with self._lock:
            return self._copy_latest()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _severity(self) -> float:
        if self._scenario == "normal":
            return 0.0
        return min(1.0, self._scenario_step / self._ramp_steps)

    def _copy_latest(self) -> dict[str, list[TelemetryReading]]:
        return {asset_id: list(readings) for asset_id, readings in self._latest.items()}

    def _now(self) -> datetime:
        return _EPOCH + timedelta(seconds=self._step * self._step_seconds)

    def _noise(self, sigma: float) -> float:
        return self._rng.gauss(0.0, sigma)

    def _snapshot(self) -> dict[str, list[TelemetryReading]]:
        scenario = self._scenario
        severity = self._severity()
        timestamp = self._now()
        readings: dict[str, list[TelemetryReading]] = {}
        for asset in self._assets:
            metrics = self._base_metrics(asset)
            self._apply_scenario(asset, metrics, scenario, severity)
            readings[asset.asset_id] = [
                TelemetryReading(
                    asset_id=asset.asset_id,
                    metric=metric,
                    value=round(value, 4),
                    unit=unit,
                    timestamp=timestamp,
                    provenance="synthetic",
                )
                for metric, (value, unit) in metrics.items()
            ]
        return readings

    # ------------------------------------------------------------------
    # Per-asset baseline generators (metric -> (value, unit))
    # ------------------------------------------------------------------
    def _base_metrics(self, asset: Asset) -> dict[str, tuple[float, str]]:
        builder = {
            AssetType.PUMP: self._pump_metrics,
            AssetType.FILTER: self._filter_metrics,
            AssetType.MOTOR: self._motor_metrics,
            AssetType.VFD: self._vfd_metrics,
            AssetType.ENERGY_RECOVERY_DEVICE: self._erd_metrics,
            AssetType.MEMBRANE_ARRAY: self._membrane_metrics,
            AssetType.CONTROL_VALVE: self._valve_metrics,
            AssetType.TRANSFORMER: self._transformer_metrics,
            AssetType.GENERATOR: self._generator_metrics,
        }[asset.asset_type]
        return builder(asset)

    def _pump_metrics(self, asset: Asset) -> dict[str, tuple[float, str]]:
        rd = asset.rated_data
        speed = (rd.rated_speed_rpm or 1480.0) * 0.995 + self._noise(3.0)
        flow = (rd.rated_flow_m3h or 100.0) * 0.96 + self._noise(1.5)
        discharge = (rd.rated_pressure_bar or 3.0) * 0.98 + self._noise(0.15)
        suction = 1.5 + self._noise(0.05)
        power = (rd.rated_power_kw or 30.0) * 0.9 + self._noise(1.0)
        current = (rd.rated_current_a or 50.0) * 0.9 + self._noise(0.8)
        return {
            "suction_pressure": (max(0.0, suction), "bar"),
            "discharge_pressure": (max(0.0, discharge), "bar"),
            "flow": (max(0.0, flow), "m3/h"),
            "speed": (max(0.0, speed), "rpm"),
            "vibration": (2.8 + self._noise(0.12), "mm/s"),
            "bearing_temp": (58.0 + self._noise(0.4), "degC"),
            "motor_power": (max(0.0, power), "kW"),
            "motor_current": (max(0.0, current), "A"),
            "cavitation_index": (0.08 + self._noise(0.01), "index"),
            "health": (100.0 + self._noise(0.2), "%"),
        }

    def _filter_metrics(self, asset: Asset) -> dict[str, tuple[float, str]]:
        rd = asset.rated_data
        flow = (rd.rated_flow_m3h or 470.0) * 0.96 + self._noise(1.5)
        return {
            "differential_pressure": (0.25 + self._noise(0.02), "bar"),
            "flow": (max(0.0, flow), "m3/h"),
            "outlet_pressure": (2.3 + self._noise(0.05), "bar"),
        }

    def _motor_metrics(self, asset: Asset) -> dict[str, tuple[float, str]]:
        rd = asset.rated_data
        power = (rd.rated_power_kw or 600.0) * 0.9 + self._noise(2.0)
        current = (rd.rated_current_a or 65.0) * 0.9 + self._noise(0.8)
        speed = (rd.rated_speed_rpm or 2980.0) * 0.995 + self._noise(3.0)
        return {
            "motor_power": (max(0.0, power), "kW"),
            "motor_current": (max(0.0, current), "A"),
            "speed": (max(0.0, speed), "rpm"),
            "winding_temp": (78.0 + self._noise(0.5), "degC"),
            "vibration": (2.2 + self._noise(0.1), "mm/s"),
        }

    def _vfd_metrics(self, asset: Asset) -> dict[str, tuple[float, str]]:
        rd = asset.rated_data
        power = (rd.rated_power_kw or 700.0) * 0.82 + self._noise(2.0)
        current = (rd.rated_current_a or 75.0) * 0.9 + self._noise(0.8)
        return {
            "output_frequency": (49.7 + self._noise(0.05), "Hz"),
            "output_power": (max(0.0, power), "kW"),
            "output_current": (max(0.0, current), "A"),
            "heatsink_temp": (48.0 + self._noise(0.5), "degC"),
        }

    def _erd_metrics(self, asset: Asset) -> dict[str, tuple[float, str]]:
        rd = asset.rated_data
        flow = (rd.rated_flow_m3h or 150.0) * 0.97 + self._noise(1.0)
        return {
            "flow": (max(0.0, flow), "m3/h"),
            "differential_pressure": (0.8 + self._noise(0.03), "bar"),
            "efficiency": ((rd.rated_efficiency_pct or 96.0) + self._noise(0.2), "%"),
            "vibration": (1.8 + self._noise(0.08), "mm/s"),
        }

    def _membrane_metrics(self, asset: Asset) -> dict[str, tuple[float, str]]:
        rd = asset.rated_data
        feed = (rd.rated_pressure_bar or 65.0) + self._noise(0.3)
        return {
            "feed_pressure": (max(0.0, feed), "bar"),
            "permeate_flow": (112.0 + self._noise(0.8), "m3/h"),
            "permeate_conductivity": (300.0 + self._noise(5.0), "uS/cm"),
            "differential_pressure": (1.5 + self._noise(0.05), "bar"),
            "normalized_permeate_flow": (100.0 + self._noise(0.3), "%"),
            "salt_passage": (1.5 + self._noise(0.03), "%"),
            "health": (100.0 + self._noise(0.2), "%"),
        }

    def _valve_metrics(self, asset: Asset) -> dict[str, tuple[float, str]]:
        return {
            "position": (55.0 + self._noise(0.5), "%"),
            "upstream_pressure": (63.0 + self._noise(0.3), "bar"),
            "downstream_pressure": (2.5 + self._noise(0.05), "bar"),
            "flow": (138.0 + self._noise(1.0), "m3/h"),
        }

    def _transformer_metrics(self, asset: Asset) -> dict[str, tuple[float, str]]:
        return {
            "online": (1.0, "bool"),
            "load": (78.0 + self._noise(1.0), "%"),
            "load_power": (1560.0 + self._noise(15.0), "kVA"),
            "oil_temp": (62.0 + self._noise(0.5), "degC"),
            "secondary_voltage": (690.0 + self._noise(1.5), "V"),
        }

    def _generator_metrics(self, asset: Asset) -> dict[str, tuple[float, str]]:
        return {
            "status": (0.0, "bool"),
            "output_power": (0.0, "kW"),
            "fuel": (95.0 + self._noise(0.2), "%"),
        }

    # ------------------------------------------------------------------
    # Scenario physics
    # ------------------------------------------------------------------
    def _apply_scenario(
        self,
        asset: Asset,
        metrics: dict[str, tuple[float, str]],
        scenario: str,
        severity: float,
    ) -> None:
        if scenario == "normal" or severity <= 0.0:
            return
        if scenario == "hpp_degradation":
            self._apply_hpp_degradation(asset, metrics, severity)
        elif scenario == "membrane_fouling":
            self._apply_membrane_fouling(asset, metrics, severity)
        elif scenario == "grid_outage":
            self._apply_grid_outage(asset, metrics, severity)

    @staticmethod
    def _scale(metrics: dict[str, tuple[float, str]], key: str, factor: float) -> None:
        if key in metrics:
            value, unit = metrics[key]
            metrics[key] = (max(0.0, value * factor), unit)

    @staticmethod
    def _offset(metrics: dict[str, tuple[float, str]], key: str, delta: float) -> None:
        if key in metrics:
            value, unit = metrics[key]
            metrics[key] = (max(0.0, value + delta), unit)

    def _apply_hpp_degradation(
        self, asset: Asset, metrics: dict[str, tuple[float, str]], severity: float
    ) -> None:
        # The developing fault is centred on the high-pressure pump; its motor
        # shows a milder sympathetic response.
        if asset.asset_id == "HPP-001":
            self._offset(metrics, "vibration", severity * 9.0)
            self._offset(metrics, "bearing_temp", severity * 34.0)
            self._scale(metrics, "suction_pressure", 1.0 - severity * 0.72)
            self._offset(metrics, "cavitation_index", severity * 0.9)
            self._offset(metrics, "health", -severity * 55.0)
            # Cavitation erodes hydraulic performance slightly.
            self._scale(metrics, "flow", 1.0 - severity * 0.08)
            self._scale(metrics, "discharge_pressure", 1.0 - severity * 0.05)
        elif asset.asset_id == "HPP-MOT-001":
            self._offset(metrics, "vibration", severity * 4.0)
            self._offset(metrics, "winding_temp", severity * 18.0)
            self._offset(metrics, "motor_current", severity * 6.0)

    def _apply_membrane_fouling(
        self, asset: Asset, metrics: dict[str, tuple[float, str]], severity: float
    ) -> None:
        if asset.asset_id == "RO-ARR-001":
            self._offset(metrics, "normalized_permeate_flow", -severity * 35.0)
            self._scale(metrics, "permeate_flow", 1.0 - severity * 0.30)
            self._offset(metrics, "permeate_conductivity", severity * 450.0)
            self._offset(metrics, "salt_passage", severity * 3.5)
            self._offset(metrics, "differential_pressure", severity * 2.5)
            self._offset(metrics, "feed_pressure", severity * 6.0)
            self._offset(metrics, "health", -severity * 40.0)
        elif asset.asset_id == "HPP-001":
            # Higher feed pressure demand loads the high-pressure pump.
            self._offset(metrics, "discharge_pressure", severity * 5.0)
            self._offset(metrics, "motor_power", severity * 25.0)

    def _apply_grid_outage(
        self, asset: Asset, metrics: dict[str, tuple[float, str]], severity: float
    ) -> None:
        if asset.asset_id == "XFMR-001":
            # Grid lost: main transformer de-energised.
            metrics["online"] = (0.0, "bool")
            self._scale(metrics, "load", 1.0 - severity)
            self._scale(metrics, "load_power", 1.0 - severity)
            self._offset(metrics, "oil_temp", -severity * 20.0)
            self._scale(metrics, "secondary_voltage", 1.0 - severity)
            return
        if asset.asset_id == "GEN-001":
            # Standby genset picks up a constrained load and burns fuel.
            metrics["status"] = (1.0, "bool")
            self._offset(metrics, "output_power", severity * 900.0)
            self._offset(metrics, "fuel", -severity * 40.0)
            return
        # Everything else runs on backup power at reduced production.
        constraint = 1.0 - severity * 0.5
        for key in ("flow", "permeate_flow", "motor_power", "output_power", "speed"):
            self._scale(metrics, key, constraint)
        self._offset(metrics, "normalized_permeate_flow", -severity * 30.0)
