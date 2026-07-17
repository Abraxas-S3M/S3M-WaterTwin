"""Resilience & Generator Command engine (advisory, read-only).

Wraps the resilience physics in :mod:`watertwin_engineering.resilience` for the
API + dashboard. On a grid-outage assessment it computes, for the reference RO
train:

* the standby-generator start probability + fuel endurance (preliminary);
* a load-shed order that keeps the high-pressure pump + essential loads last;
* the service-continuity duration under grid loss; and
* a resilience-criticality ranking of assets.

It then builds a single advisory recommendation ("prioritise GEN-001 to the HP
pump + essential loads") that the API routes through the *existing* recommendation
+ audit path -- created ``pending`` operator approval, with the read-only control
boundary intact. Every figure is preliminary/estimated; nothing here writes to
any control system.
"""

from __future__ import annotations

from uuid import uuid4

from canonical_water_model import (
    ApprovalStatus,
    ControlBoundary,
    DataProvenance,
    Evidence,
    GeneratorStatus,
    LoadShedItem,
    LoadShedPlan,
    RankedCause,
    RecommendationCard,
    ResilienceCriticality,
    ServiceContinuity,
    now_iso,
)
from watertwin_engineering import (
    fuel_endurance_hours,
    generator_start_probability,
    load_shed_priority,
    resilience_criticality_score,
    service_continuity_hours,
)

from .water_quality import FACILITY_ID, TRAIN_ID

#: Deterministic id so repeated grid-outage assessments are idempotent.
GRID_OUTAGE_RECOMMENDATION_ID = "rec-resilience-grid-outage"

#: Standby generator (synthetic reference).
GENERATOR = {
    "generator_id": "GEN-001",
    "name": "Standby Diesel Generator",
    "rated_power_kw": 1100.0,
    "tank_capacity_l": 4000.0,
    "consumption_rate_l_per_h": 230.0,  # at full load
    "battery_fraction": 0.86,
    "days_since_last_test": 22.0,
    "maintenance_due": False,
    "fuel_level_fraction": 0.72,
    "battery_bridge_minutes": 12.0,
}

#: Electrical loads on the train, with resilience drivers (synthetic).
LOAD_ASSETS: list[dict] = [
    {
        "asset_id": "AST-HPP-01",
        "asset_name": "High-Pressure Pump A",
        "asset_type": "hp_pump",
        "load_kw": 900.0,
        "priority": "critical",
        "customer_or_production_impact": 0.95,
        "failure_probability": 0.35,
        "recovery_time_hours": 36.0,
        "dependency_centrality": 0.95,
        "backup_deficiency": 0.6,
    },
    {
        "asset_id": "AST-DOSE-01",
        "asset_name": "Dosing Skid (antiscalant/acid)",
        "asset_type": "dosing_pump",
        "load_kw": 40.0,
        "priority": "essential",
        "customer_or_production_impact": 0.6,
        "failure_probability": 0.2,
        "recovery_time_hours": 8.0,
        "dependency_centrality": 0.7,
        "backup_deficiency": 0.3,
    },
    {
        "asset_id": "AST-BOOST-01",
        "asset_name": "Booster / Permeate Pump",
        "asset_type": "booster_pump",
        "load_kw": 130.0,
        "priority": "essential",
        "customer_or_production_impact": 0.55,
        "failure_probability": 0.18,
        "recovery_time_hours": 10.0,
        "dependency_centrality": 0.6,
        "backup_deficiency": 0.4,
    },
    {
        "asset_id": "AST-CIP-01",
        "asset_name": "CIP System",
        "asset_type": "transfer_pump",
        "load_kw": 150.0,
        "priority": "non_essential",
        "customer_or_production_impact": 0.2,
        "failure_probability": 0.1,
        "recovery_time_hours": 4.0,
        "dependency_centrality": 0.2,
        "backup_deficiency": 0.2,
    },
    {
        "asset_id": "AST-AUX-01",
        "asset_name": "Building / Auxiliary Loads",
        "asset_type": "sensor",
        "load_kw": 60.0,
        "priority": "non_essential",
        "customer_or_production_impact": 0.15,
        "failure_probability": 0.08,
        "recovery_time_hours": 2.0,
        "dependency_centrality": 0.15,
        "backup_deficiency": 0.1,
    },
]


def generator_status(load_fraction: float | None = None) -> GeneratorStatus:
    """Preliminary generator readiness + fuel endurance at ``load_fraction``."""
    start_prob = generator_start_probability(
        battery=GENERATOR["battery_fraction"],
        last_test_days=GENERATOR["days_since_last_test"],
        maintenance_due=GENERATOR["maintenance_due"],
    )
    if load_fraction is None:
        load_fraction = 0.85
    fuel_litres = GENERATOR["fuel_level_fraction"] * GENERATOR["tank_capacity_l"]
    endurance = fuel_endurance_hours(
        fuel_level_litres=fuel_litres,
        consumption_rate_l_per_h=GENERATOR["consumption_rate_l_per_h"],
        load_fraction=load_fraction,
    )
    return GeneratorStatus(
        generator_id=GENERATOR["generator_id"],
        name=GENERATOR["name"],
        start_probability=start_prob,
        battery_fraction=GENERATOR["battery_fraction"],
        days_since_last_test=GENERATOR["days_since_last_test"],
        maintenance_due=GENERATOR["maintenance_due"],
        fuel_level_fraction=GENERATOR["fuel_level_fraction"],
        consumption_rate_l_per_h=GENERATOR["consumption_rate_l_per_h"],
        load_fraction=round(load_fraction, 4),
        fuel_endurance_hours=endurance,
        rated_power_kw=GENERATOR["rated_power_kw"],
        provenance=DataProvenance.preliminary,
    )


def criticality_ranking() -> list[ResilienceCriticality]:
    """Resilience-criticality ranking of assets (highest impact/risk first)."""
    ranked: list[ResilienceCriticality] = []
    for asset in LOAD_ASSETS:
        score = resilience_criticality_score(
            customer_or_production_impact=asset["customer_or_production_impact"],
            failure_probability=asset["failure_probability"],
            recovery_time_hours=asset["recovery_time_hours"],
            dependency_centrality=asset["dependency_centrality"],
            backup_deficiency=asset["backup_deficiency"],
        )
        ranked.append(
            ResilienceCriticality(
                asset_id=asset["asset_id"],
                asset_name=asset["asset_name"],
                criticality_score=score,
                customer_or_production_impact=asset["customer_or_production_impact"],
                failure_probability=asset["failure_probability"],
                recovery_time_hours=asset["recovery_time_hours"],
                dependency_centrality=asset["dependency_centrality"],
                backup_deficiency=asset["backup_deficiency"],
                provenance=DataProvenance.preliminary,
            )
        )
    ranked.sort(key=lambda c: c.criticality_score, reverse=True)
    for i, c in enumerate(ranked, start=1):
        c.rank = i
    return ranked


def load_shed_plan(available_generation_kw: float) -> LoadShedPlan:
    """Preliminary load-shed plan sustaining critical loads under ``available_generation_kw``."""
    ordered = load_shed_priority(LOAD_ASSETS)
    total_load = sum(float(a["load_kw"]) for a in LOAD_ASSETS)

    # Retain loads most-critical-first (shed_order descending) within capacity.
    retained_ids: set[str] = set()
    retained_kw = 0.0
    for asset in sorted(ordered, key=lambda a: a["shed_order"], reverse=True):
        load = float(asset["load_kw"])
        if retained_kw + load <= available_generation_kw + 1e-6:
            retained_kw += load
            retained_ids.add(asset["asset_id"])

    items: list[LoadShedItem] = []
    for asset in ordered:
        items.append(
            LoadShedItem(
                asset_id=asset["asset_id"],
                asset_name=asset.get("asset_name"),
                load_kw=float(asset["load_kw"]),
                priority=str(asset["priority"]),
                shed_order=int(asset["shed_order"]),
                retained=asset["asset_id"] in retained_ids,
            )
        )

    critical_sustained = all(
        i.retained for i in items if i.priority in ("critical", "essential")
    )
    return LoadShedPlan(
        available_generation_kw=round(available_generation_kw, 2),
        total_load_kw=round(total_load, 2),
        retained_load_kw=round(retained_kw, 2),
        shed_load_kw=round(total_load - retained_kw, 2),
        items=items,
        critical_loads_sustained=critical_sustained,
        provenance=DataProvenance.preliminary,
    )


def assess_grid_outage(
    fuel_level_fraction: float | None = None,
    battery_bridge_minutes: float | None = None,
) -> dict:
    """Assess the grid-outage scenario for the reference train.

    Computes generator readiness + fuel endurance, the load-shed plan, the
    service-continuity duration and the criticality ranking, then builds a single
    advisory recommendation to prioritise the generator to the HP pump. All
    outputs are preliminary/estimated and advisory only.
    """
    if fuel_level_fraction is not None:
        GENERATOR["fuel_level_fraction"] = max(0.0, min(1.0, fuel_level_fraction))
    bridge = (
        battery_bridge_minutes
        if battery_bridge_minutes is not None
        else GENERATOR["battery_bridge_minutes"]
    )

    gen_start = generator_start_probability(
        battery=GENERATOR["battery_fraction"],
        last_test_days=GENERATOR["days_since_last_test"],
        maintenance_due=GENERATOR["maintenance_due"],
    )
    generator_available = gen_start >= 0.5

    # Available generation when the set starts; shed to fit critical loads.
    available_generation = GENERATOR["rated_power_kw"] if generator_available else 0.0
    plan = load_shed_plan(available_generation)

    # Load fraction the generator actually carries drives fuel endurance.
    load_fraction = (
        min(1.0, plan.retained_load_kw / GENERATOR["rated_power_kw"])
        if GENERATOR["rated_power_kw"] > 0
        else 0.0
    )
    gen = generator_status(load_fraction=load_fraction)

    continuity_hours = service_continuity_hours(
        {
            "generator_available": generator_available,
            "fuel_endurance_hours": gen.fuel_endurance_hours,
            "battery_bridge_minutes": bridge,
            "critical_loads_sustained": plan.critical_loads_sustained,
        }
    )
    if not generator_available:
        limiting = "generator start failure — battery bridge only"
    elif plan.critical_loads_sustained:
        limiting = "generator fuel endurance"
    else:
        limiting = "insufficient generation for critical loads"

    continuity = ServiceContinuity(
        scenario="grid_outage",
        service_continuity_hours=continuity_hours,
        limiting_factor=limiting,
        generator_available=generator_available,
        generator_start_probability=gen_start,
        fuel_endurance_hours=gen.fuel_endurance_hours,
        battery_bridge_minutes=float(bridge),
        critical_loads_sustained=plan.critical_loads_sustained,
        provenance=DataProvenance.preliminary,
    )

    criticality = criticality_ranking()
    recommendation = build_resilience_recommendation(gen, plan, continuity, criticality)

    return {
        "scenario": "grid_outage",
        "generator": gen,
        "load_shed_plan": plan,
        "service_continuity": continuity,
        "criticality": criticality,
        "recommendation": recommendation,
    }


def build_resilience_recommendation(
    generator: GeneratorStatus,
    plan: LoadShedPlan,
    continuity: ServiceContinuity,
    criticality: list[ResilienceCriticality],
) -> RecommendationCard:
    """Build the advisory grid-outage recommendation (pending, no control write).

    Prioritises the standby generator to the high-pressure pump + essential loads
    and sheds non-essential loads. Created ``pending`` operator approval with the
    read-only control boundary intact; the id is deterministic so repeated
    assessments are idempotent.
    """
    shed = [i for i in plan.items if not i.retained]
    shed_names = ", ".join(i.asset_name or i.asset_id for i in shed) or "none"
    top = criticality[0] if criticality else None
    evidence = Evidence(
        telemetry_window="grid-outage scenario (synthetic resilience assessment)",
        assets_reviewed=[i.asset_id for i in plan.items],
        documents_reviewed=[],
        simulation_ids=[],
        assumptions=[
            "Preliminary resilience model (advisory, not validated).",
            "Generator start probability, fuel endurance and service-continuity "
            "duration are preliminary estimates on synthetic data, not guaranteed "
            "availability or run-time.",
        ],
        data_timestamp=now_iso(),
    )
    summary = (
        f"Grid outage: prioritise {generator.generator_id} to the high-pressure "
        f"pump + essential loads; ~{continuity.service_continuity_hours:.1f} h "
        f"service continuity (generator start probability "
        f"{generator.start_probability:.0%}, fuel endurance "
        f"{generator.fuel_endurance_hours:.1f} h)."
    )
    action = (
        f"Prioritise {generator.generator_id} to the HP pump (AST-HPP-01) and "
        f"essential loads; shed non-essential loads ({shed_names}). Verify fuel "
        f"level and battery bridge. Advisory only — operator approval required, "
        f"no control write."
    )
    ranked_causes = []
    if top is not None:
        ranked_causes.append(
            RankedCause(
                cause=f"{top.asset_name or top.asset_id} is the most critical load",
                probability=round(min(1.0, top.criticality_score / 100.0), 3),
                evidence=(
                    f"resilience-criticality score {top.criticality_score:.0f}/100 "
                    f"(impact {top.customer_or_production_impact:.2f}, "
                    f"failure prob {top.failure_probability:.2f})"
                ),
            )
        )
    return RecommendationCard(
        recommendation_id=GRID_OUTAGE_RECOMMENDATION_ID,
        packet_id=f"pkt-resilience-{uuid4().hex[:12]}",
        facility_id=FACILITY_ID,
        train_id=TRAIN_ID,
        asset_id="AST-HPP-01",
        summary=summary,
        ranked_causes=ranked_causes,
        recommended_action=action,
        confidence=round(generator.start_probability, 3),
        evidence=evidence,
        control_boundary=ControlBoundary(),
        approval_status=ApprovalStatus.pending,
        source_engine_status="resilience: preliminary",
        created_at=now_iso(),
    )
