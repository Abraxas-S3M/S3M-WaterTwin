"""Tests for the RO plant seed and the synthetic telemetry generator."""

from __future__ import annotations

from watertwin.models import Criticality, TelemetryReading
from watertwin.plant_seed import (
    FACILITY_ID,
    TRAIN_ID,
    seed_assets,
    seed_sampling_points,
    seed_streams,
)
from watertwin.telemetry import SyntheticPlant


def _reading(snapshot: dict[str, list[TelemetryReading]], asset_id: str, metric: str) -> float:
    for reading in snapshot[asset_id]:
        if reading.metric == metric:
            return reading.value
    raise AssertionError(f"metric {metric!r} not found for asset {asset_id!r}")


def test_facility_and_train_ids_are_stable() -> None:
    assert FACILITY_ID == "RO-FACILITY-001"
    assert TRAIN_ID == "RO-TRAIN-001"


def test_seed_assets_contents() -> None:
    assets = seed_assets()
    assert len(assets) >= 14

    by_id = {a.asset_id: a for a in assets}

    # The key critical asset must be present and marked critical.
    assert "HPP-001" in by_id
    assert by_id["HPP-001"].criticality == Criticality.CRITICAL

    # Energy-recovery device and membrane array must exist.
    assert "ERD-001" in by_id
    assert "RO-ARR-001" in by_id

    # HPP sub-assets are parented to the high-pressure pump.
    assert by_id["HPP-MOT-001"].parent_id == "HPP-001"
    assert by_id["HPP-VFD-001"].parent_id == "HPP-001"


def test_seed_streams_and_sampling_points() -> None:
    streams = seed_streams()
    assert len(streams) == 5
    stream_names = {s.name for s in streams}
    assert {"seawater_feed", "pretreated_feed", "ro_feed", "permeate"} <= stream_names

    points = seed_sampling_points()
    assert len(points) == 7
    for point in points:
        assert point.point_id.startswith("SP-")


def test_scenarios_registered() -> None:
    assert SyntheticPlant.SCENARIOS == (
        "normal",
        "hpp_degradation",
        "membrane_fouling",
        "grid_outage",
    )


def test_tick_normal_returns_synthetic_readings_for_every_asset() -> None:
    plant = SyntheticPlant(seed=7)
    asset_ids = {a.asset_id for a in seed_assets()}

    snapshot = plant.tick()

    assert set(snapshot.keys()) == asset_ids
    for asset_id in asset_ids:
        readings = snapshot[asset_id]
        assert readings, f"no readings for {asset_id}"
        for reading in readings:
            assert reading.provenance == "synthetic"


def test_hpp_degradation_raises_vibration_and_bearing_temp_then_resets() -> None:
    plant = SyntheticPlant(seed=7)

    # Establish a normal baseline for the high-pressure pump.
    for _ in range(5):
        plant.tick()
    baseline = plant.latest()
    base_vibration = _reading(baseline, "HPP-001", "vibration")
    base_bearing_temp = _reading(baseline, "HPP-001", "bearing_temp")

    # Inject the degradation fault and let its severity ramp up.
    plant.set_scenario("hpp_degradation")
    for _ in range(20):
        plant.tick()
    degraded = plant.latest()

    assert _reading(degraded, "HPP-001", "vibration") > base_vibration
    assert _reading(degraded, "HPP-001", "bearing_temp") > base_bearing_temp
    # Suction decline drives the cavitation index up and health down.
    assert _reading(degraded, "HPP-001", "cavitation_index") > _reading(
        baseline, "HPP-001", "cavitation_index"
    )
    assert _reading(degraded, "HPP-001", "health") < _reading(baseline, "HPP-001", "health")

    # reset() returns the plant to a normal state.
    restored = plant.reset()
    assert plant.scenario == "normal"
    assert plant.severity == 0.0
    assert _reading(restored, "HPP-001", "vibration") < _reading(degraded, "HPP-001", "vibration")
    assert _reading(restored, "HPP-001", "bearing_temp") < _reading(
        degraded, "HPP-001", "bearing_temp"
    )


def test_membrane_fouling_physics() -> None:
    plant = SyntheticPlant(seed=11)
    for _ in range(3):
        plant.tick()
    baseline = plant.latest()

    plant.set_scenario("membrane_fouling")
    for _ in range(20):
        plant.tick()
    fouled = plant.latest()

    assert _reading(fouled, "RO-ARR-001", "normalized_permeate_flow") < _reading(
        baseline, "RO-ARR-001", "normalized_permeate_flow"
    )
    assert _reading(fouled, "RO-ARR-001", "permeate_conductivity") > _reading(
        baseline, "RO-ARR-001", "permeate_conductivity"
    )
    assert _reading(fouled, "RO-ARR-001", "differential_pressure") > _reading(
        baseline, "RO-ARR-001", "differential_pressure"
    )
    assert _reading(fouled, "RO-ARR-001", "salt_passage") > _reading(
        baseline, "RO-ARR-001", "salt_passage"
    )


def test_grid_outage_takes_transformer_offline_and_starts_generator() -> None:
    plant = SyntheticPlant(seed=3)
    plant.set_scenario("grid_outage")
    for _ in range(20):
        plant.tick()
    outage = plant.latest()

    assert _reading(outage, "XFMR-001", "online") == 0.0
    assert _reading(outage, "GEN-001", "status") == 1.0
    # Backup power constrains production: permeate flow is reduced.
    normal_plant = SyntheticPlant(seed=3)
    normal_plant.tick()
    normal = normal_plant.latest()
    assert _reading(outage, "RO-ARR-001", "permeate_flow") < _reading(
        normal, "RO-ARR-001", "permeate_flow"
    )


def test_determinism_with_same_seed() -> None:
    a = SyntheticPlant(seed=99)
    b = SyntheticPlant(seed=99)
    for _ in range(5):
        a.tick()
        b.tick()
    snap_a = a.latest()
    snap_b = b.latest()
    for asset_id, readings in snap_a.items():
        for r_a, r_b in zip(readings, snap_b[asset_id], strict=True):
            assert r_a.metric == r_b.metric
            assert r_a.value == r_b.value


def test_thread_safe_concurrent_ticks() -> None:
    import threading

    plant = SyntheticPlant(seed=5)
    errors: list[Exception] = []

    def worker() -> None:
        try:
            for _ in range(50):
                plant.tick()
                plant.latest()
        except Exception as exc:  # noqa: BLE001 - surfaced via assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(plant.latest()) == len(seed_assets())
