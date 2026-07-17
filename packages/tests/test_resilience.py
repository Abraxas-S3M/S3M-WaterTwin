"""Tests for the resilience & standby-generator physics.

Locks the invariants the resilience command layer depends on: fuel endurance
falls as load rises, generator start probability is a preliminary value in
[0, 1], the criticality score ranks higher-impact/higher-risk assets first, the
load-shed order keeps the high-pressure pump last, and service continuity holds
only for the battery bridge when the generator does not start.
"""

from __future__ import annotations

import pytest

from watertwin_engineering import (
    fuel_endurance_hours,
    generator_start_probability,
    load_shed_priority,
    resilience_criticality_score,
    service_continuity_hours,
)
from watertwin_engineering.resilience import PRELIMINARY


def test_fuel_endurance_decreases_as_load_increases() -> None:
    low = fuel_endurance_hours(2000.0, 200.0, 0.3)
    mid = fuel_endurance_hours(2000.0, 200.0, 0.6)
    high = fuel_endurance_hours(2000.0, 200.0, 0.9)
    assert low > mid > high
    assert high > 0.0


def test_generator_start_probability_in_unit_interval_and_preliminary() -> None:
    healthy = generator_start_probability(battery=1.0, last_test_days=5, maintenance_due=False)
    degraded = generator_start_probability(battery=0.2, last_test_days=120, maintenance_due=True)
    for p in (healthy, degraded):
        assert 0.0 <= p <= 1.0
    # A healthy set is more likely to start than a neglected one.
    assert healthy > degraded
    # The physics is labelled preliminary (never a guaranteed availability).
    assert PRELIMINARY == "preliminary"


def test_criticality_ranks_higher_impact_and_risk_first() -> None:
    hp_pump = resilience_criticality_score(
        customer_or_production_impact=0.95,
        failure_probability=0.5,
        recovery_time_hours=36.0,
        dependency_centrality=0.9,
        backup_deficiency=1.0,
    )
    aux = resilience_criticality_score(
        customer_or_production_impact=0.15,
        failure_probability=0.08,
        recovery_time_hours=2.0,
        dependency_centrality=0.15,
        backup_deficiency=0.1,
    )
    assert hp_pump > aux
    assert 0.0 <= aux <= hp_pump <= 100.0


def test_load_shed_priority_keeps_hp_pump_last() -> None:
    assets = [
        {"asset_id": "AST-HPP-01", "load_kw": 900, "priority": "critical", "asset_type": "hp_pump"},
        {"asset_id": "AST-DOSE-01", "load_kw": 40, "priority": "essential"},
        {"asset_id": "AST-CIP-01", "load_kw": 150, "priority": "non_essential"},
        {"asset_id": "AST-AUX-01", "load_kw": 60, "priority": "non_essential"},
    ]
    ordered = load_shed_priority(assets)
    by_id = {a["asset_id"]: a["shed_order"] for a in ordered}
    max_order = max(by_id.values())
    # The HP pump is shed last (highest shed_order).
    assert by_id["AST-HPP-01"] == max_order
    # Non-essential loads are shed before essential/critical ones.
    assert by_id["AST-CIP-01"] < by_id["AST-DOSE-01"] < by_id["AST-HPP-01"]


def test_service_continuity_uses_battery_only_without_generator() -> None:
    with_gen = service_continuity_hours(
        {
            "generator_available": True,
            "fuel_endurance_hours": 10.0,
            "battery_bridge_minutes": 15.0,
            "critical_loads_sustained": True,
        }
    )
    no_gen = service_continuity_hours(
        {
            "generator_available": False,
            "fuel_endurance_hours": 10.0,
            "battery_bridge_minutes": 15.0,
        }
    )
    assert with_gen == pytest.approx(10.25)
    assert no_gen == pytest.approx(0.25)
    assert with_gen > no_gen
