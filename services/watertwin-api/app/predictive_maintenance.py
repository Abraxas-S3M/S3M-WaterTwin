"""Predictive Maintenance engine (advisory, read-only).

For each critical asset this module assembles the equipment-intelligence view --
component health, preliminary remaining-useful-life (RUL), failure probability,
operating envelope, causal root-cause ranking and a maintenance-priority rank --
by orchestrating the pure physics in :mod:`watertwin_engineering` and the
membrane intelligence in :mod:`app.membrane` (which itself reuses the Water
Quality layer). It then produces PdM recommendations (predicted failure mode,
time-to-intervention, a low-demand maintenance window, spares, expected
downtime, maintenance cost and avoided-failure cost).

Everything here is **advisory and preliminary**. RUL, failure probability and
avoided-cost are screening-grade engineering estimates -- never validated or
guaranteed -- and are stamped ``provenance = preliminary``. PdM recommendations
are built ``pending`` operator approval with the read-only control boundary
intact; the API persists and audits them through the *existing* recommendation +
audit path. Nothing here writes to any control system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from canonical_water_model import (
    ComponentHealth,
    ControlBoundary,
    DataProvenance,
    Evidence,
    FailureProbability,
    HealthBand,
    HealthContribution,
    MaintenancePriority,
    OperatingEnvelope,
    PdMRecommendation,
    RankedCause,
    RecommendationCard,
    RemainingUsefulLife,
    RootCauseRanking,
    now_iso,
)
from watertwin_engineering import (
    component_health,
    failure_probability,
    maintenance_priority,
    operating_envelope_score,
    remaining_useful_life_days,
    root_cause_rank,
)

from . import membrane
from .water_quality import FACILITY_ID, TRAIN_ID

#: Default fouling severity used to drive the membrane + HP-pump scenario when a
#: caller does not pass one (mirrors the WQ default; read-only what-if only).
DEFAULT_FOULING = 0.35


@dataclass
class AssetSpec:
    """Synthetic descriptor for a critical asset in the reference RO train."""

    asset_id: str
    name: str
    component_type: str  # equipment.COMPONENT_TYPES value (or "membrane")
    criticality: str
    anomaly_score: float
    telemetry: dict[str, float]
    health_trend: list[float]
    duty_cycle: float
    maintenance_age_days: float
    recommended_interval_days: float
    comparable_asset_factor: float
    consequence: float
    production_impact: float
    redundancy: float
    spares_available: bool
    safety_or_wq_weight: float
    predicted_failure_mode: str
    spares_required: list[str]
    expected_downtime_hours: float
    maintenance_cost: float
    avoided_failure_cost: float
    envelope_history: list[dict[str, float]] = field(default_factory=list)
    root_cause_telemetry: dict[str, float] = field(default_factory=dict)
    root_cause_context: dict[str, float] = field(default_factory=dict)


def _pump_envelope_history() -> list[dict[str, float]]:
    base = {"bep_flow_m3h": 500.0, "max_pressure_bar": 70.0, "temp_limit_c": 45.0}
    samples = [
        {"flow_m3h": 500, "pressure_bar": 62, "temperature_c": 34},
        {"flow_m3h": 505, "pressure_bar": 63, "temperature_c": 35},
        {"flow_m3h": 330, "pressure_bar": 68, "temperature_c": 38},
        {"flow_m3h": 480, "pressure_bar": 72, "temperature_c": 41},
        {"flow_m3h": 495, "pressure_bar": 64, "temperature_c": 47},
    ]
    return [{**base, **s} for s in samples]


#: The critical assets covered by the PdM engine. Electrical / generator /
#: resilience assets are intentionally out of scope for this work package.
ASSETS: dict[str, AssetSpec] = {
    "AST-HPP-01": AssetSpec(
        asset_id="AST-HPP-01",
        name="High-Pressure Pump A",
        component_type="pump",
        criticality="critical",
        anomaly_score=0.61,
        telemetry={
            "current_imbalance_pct": 4.0,
            "winding_temp_c": 150.0,
            "winding_temp_limit_c": 155.0,
            "vibration_mm_s": 6.4,
            "vibration_limit_mm_s": 4.5,
            "bearing_temp_c": 92.0,
            "bearing_temp_limit_c": 90.0,
            "seal_leakage_ml_min": 3.0,
            "efficiency_drift_pct": 6.0,
        },
        health_trend=[74, 71, 69, 66, 63],
        duty_cycle=0.82,
        maintenance_age_days=220.0,
        recommended_interval_days=365.0,
        comparable_asset_factor=0.9,
        consequence=0.85,
        production_impact=0.9,
        redundancy=1.0,
        spares_available=True,
        safety_or_wq_weight=1.2,
        predicted_failure_mode="Progressive hydraulic-efficiency loss / bearing wear",
        spares_required=["Drive-end bearing set", "Mechanical seal cartridge"],
        expected_downtime_hours=10.0,
        maintenance_cost=28000.0,
        avoided_failure_cost=185000.0,
        envelope_history=_pump_envelope_history(),
        root_cause_telemetry={"power_pct_change": 11.0, "production_pct_change": -6.0},
        root_cause_context={
            "normalized_dp_rise_pct": 12.0,
            "normalized_salt_passage_rise_pct": 8.0,
            "pump_curve_efficiency_deviation_pct": 3.0,
            "feed_salinity_rise_pct": 2.0,
            "valve_position_error_pct": 1.0,
            "sensor_consistency": 0.95,
            "last_cip_days": 45.0,
            "days_since_pump_service": 220.0,
            "days_since_calibration": 90.0,
        },
    ),
    "AST-MEMB-01": AssetSpec(
        asset_id="AST-MEMB-01",
        name="RO Membrane Array (Train 1)",
        component_type="membrane",
        criticality="critical",
        anomaly_score=0.48,
        telemetry={},
        health_trend=[],  # membrane health/RUL come from the membrane engine
        duty_cycle=0.75,
        maintenance_age_days=120.0,
        recommended_interval_days=membrane.CIP_INTERVAL_DAYS,
        comparable_asset_factor=1.0,
        consequence=0.75,
        production_impact=0.8,
        redundancy=0.0,
        spares_available=False,
        safety_or_wq_weight=1.4,
        predicted_failure_mode="Irreversible fouling / salt-passage breakthrough",
        spares_required=["RO elements (tail vessels)", "CIP chemicals"],
        expected_downtime_hours=16.0,
        maintenance_cost=42000.0,
        avoided_failure_cost=160000.0,
        root_cause_telemetry={"power_pct_change": 9.0, "production_pct_change": -5.0},
        root_cause_context={
            "normalized_dp_rise_pct": 14.0,
            "normalized_salt_passage_rise_pct": 9.0,
            "feed_salinity_rise_pct": 3.0,
            "sensor_consistency": 0.96,
            "last_cip_days": 120.0,
        },
    ),
    "AST-ERD-01": AssetSpec(
        asset_id="AST-ERD-01",
        name="Energy Recovery Device",
        component_type="erd",
        criticality="high",
        anomaly_score=0.32,
        telemetry={"transfer_efficiency_pct": 92.5, "rated_transfer_efficiency_pct": 96.0},
        health_trend=[92, 90, 89, 88, 87],
        duty_cycle=0.7,
        maintenance_age_days=140.0,
        recommended_interval_days=540.0,
        comparable_asset_factor=1.05,
        consequence=0.5,
        production_impact=0.35,
        redundancy=0.0,
        spares_available=True,
        safety_or_wq_weight=1.0,
        predicted_failure_mode="Rotor/seal wear reducing transfer efficiency",
        spares_required=["ERD rotor seal kit"],
        expected_downtime_hours=6.0,
        maintenance_cost=15000.0,
        avoided_failure_cost=60000.0,
        root_cause_telemetry={"power_pct_change": 3.0, "production_pct_change": -1.0},
        root_cause_context={"sensor_consistency": 0.97, "days_since_calibration": 60.0},
    ),
    "AST-CF-01": AssetSpec(
        asset_id="AST-CF-01",
        name="Cartridge Filter Bank",
        component_type="filter",
        criticality="medium",
        anomaly_score=0.28,
        telemetry={"normalized_dp": 1.9, "dp_bar": 0.57, "clean_dp_bar": 0.3},
        health_trend=[95, 92, 88, 84, 80],
        duty_cycle=0.65,
        maintenance_age_days=45.0,
        recommended_interval_days=90.0,
        comparable_asset_factor=1.0,
        consequence=0.35,
        production_impact=0.4,
        redundancy=0.0,
        spares_available=True,
        safety_or_wq_weight=1.0,
        predicted_failure_mode="Cartridge plugging (high differential pressure)",
        spares_required=["Cartridge filter set (5 µm)"],
        expected_downtime_hours=3.0,
        maintenance_cost=6000.0,
        avoided_failure_cost=22000.0,
        root_cause_telemetry={"power_pct_change": 1.0, "production_pct_change": -1.0},
        root_cause_context={"sensor_consistency": 0.98},
    ),
    "AST-HPP-02": AssetSpec(
        asset_id="AST-HPP-02",
        name="High-Pressure Pump B (standby)",
        component_type="pump",
        criticality="high",
        anomaly_score=0.12,
        telemetry={
            "vibration_mm_s": 2.4,
            "vibration_limit_mm_s": 4.5,
            "bearing_temp_c": 70.0,
            "bearing_temp_limit_c": 90.0,
            "efficiency_drift_pct": 1.0,
        },
        health_trend=[96, 95, 95, 94, 94],
        duty_cycle=0.25,
        maintenance_age_days=60.0,
        recommended_interval_days=365.0,
        comparable_asset_factor=1.1,
        consequence=0.6,
        production_impact=0.2,
        redundancy=1.0,
        spares_available=True,
        safety_or_wq_weight=1.0,
        predicted_failure_mode="No active degradation mode (standby duty)",
        spares_required=[],
        expected_downtime_hours=8.0,
        maintenance_cost=24000.0,
        avoided_failure_cost=40000.0,
        envelope_history=_pump_envelope_history(),
        root_cause_telemetry={"power_pct_change": 0.0, "production_pct_change": 0.0},
        root_cause_context={"sensor_consistency": 0.99},
    ),
}


def list_asset_ids() -> list[str]:
    """Return the ids of all critical assets covered by the PdM engine."""
    return list(ASSETS)


def _spec(asset_id: str) -> AssetSpec:
    spec = ASSETS.get(asset_id)
    if spec is None:
        raise KeyError(asset_id)
    return spec


def component_health_for(asset_id: str, fouling: float = DEFAULT_FOULING) -> ComponentHealth:
    """Component health for an asset (membrane assets use the membrane engine)."""
    spec = _spec(asset_id)
    if spec.component_type == "membrane":
        mh = membrane.compute_membrane_health(fouling, asset_id=asset_id)
        return ComponentHealth(
            asset_id=asset_id,
            component_type="membrane",
            score=mh.score,
            band=mh.band,
            contributions=mh.contributions,
            provenance=DataProvenance.preliminary,
        )
    result = component_health(spec.component_type, spec.telemetry)
    return ComponentHealth(
        asset_id=asset_id,
        component_type=result.component_type,
        score=result.score,
        band=HealthBand(result.band),
        contributions=[
            HealthContribution(factor=c.factor, delta=c.delta, detail=c.detail)
            for c in result.contributions
        ],
        provenance=DataProvenance.preliminary,
    )


def _health_score_and_band(asset_id: str, fouling: float) -> tuple[float, HealthBand]:
    ch = component_health_for(asset_id, fouling)
    return ch.score, ch.band


def rul_for(asset_id: str, fouling: float = DEFAULT_FOULING) -> RemainingUsefulLife:
    """Preliminary remaining-useful-life for an asset (with an uncertainty band)."""
    spec = _spec(asset_id)
    if spec.component_type == "membrane":
        mh = membrane.compute_membrane_health(fouling, asset_id=asset_id)
        assert mh.rul is not None
        return mh.rul
    rul = remaining_useful_life_days(
        health_trend=spec.health_trend,
        duty_cycle=spec.duty_cycle,
        maintenance_age_days=spec.maintenance_age_days,
        recommended_interval_days=spec.recommended_interval_days,
        comparable_asset_factor=spec.comparable_asset_factor,
    )
    return RemainingUsefulLife(
        asset_id=asset_id,
        rul_days=rul.rul_days,
        lower_days=rul.lower_days,
        upper_days=rul.upper_days,
        method=rul.method,
        basis=rul.basis,
        provenance=DataProvenance.preliminary,
    )


def failure_probability_for(
    asset_id: str, fouling: float = DEFAULT_FOULING
) -> FailureProbability:
    """Preliminary failure probability over fixed horizons for an asset."""
    spec = _spec(asset_id)
    _, band = _health_score_and_band(asset_id, fouling)
    rul = rul_for(asset_id, fouling)
    fp = failure_probability(band.value, spec.anomaly_score, rul.rul_days)
    return FailureProbability(
        asset_id=asset_id,
        horizons=fp.horizons,
        predicted_failure_mode=spec.predicted_failure_mode,
        provenance=DataProvenance.preliminary,
    )


def envelope_for(asset_id: str) -> OperatingEnvelope:
    """Operating-envelope regime fractions for an asset."""
    spec = _spec(asset_id)
    history = spec.envelope_history or _pump_envelope_history()
    env = operating_envelope_score(history)
    return OperatingEnvelope(
        asset_id=asset_id,
        samples=env.samples,
        at_bep_fraction=env.at_bep_fraction,
        low_flow_fraction=env.low_flow_fraction,
        high_pressure_fraction=env.high_pressure_fraction,
        excess_temperature_fraction=env.excess_temperature_fraction,
        cavitation_risk_fraction=env.cavitation_risk_fraction,
        provenance=DataProvenance.preliminary,
    )


def root_cause_for(asset_id: str) -> RootCauseRanking:
    """Causal root-cause ranking for an asset (probabilities sum to ~1.0)."""
    spec = _spec(asset_id)
    ranked = root_cause_rank(
        {"asset_id": asset_id, "asset_type": spec.component_type},
        spec.root_cause_telemetry,
        spec.root_cause_context,
    )
    return RootCauseRanking(
        asset_id=asset_id,
        ranked_causes=[
            RankedCause(cause=rc.label, probability=rc.probability, evidence=rc.evidence)
            for rc in ranked
        ],
        provenance=DataProvenance.preliminary,
    )


def priority_for(asset_id: str, fouling: float = DEFAULT_FOULING) -> MaintenancePriority:
    """Maintenance-priority rank score for an asset (higher = more urgent)."""
    spec = _spec(asset_id)
    fp = failure_probability_for(asset_id, fouling)
    result = maintenance_priority(
        failure_prob=fp.horizons["30d"],
        consequence=spec.consequence,
        production_impact=spec.production_impact,
        redundancy=spec.redundancy,
        spares_available=spec.spares_available,
        safety_or_wq_weight=spec.safety_or_wq_weight,
    )
    return MaintenancePriority(
        asset_id=asset_id,
        rank_score=result.rank_score,
        factors=result.factors,
        provenance=DataProvenance.preliminary,
    )


def _maintenance_window(time_to_intervention_days: float) -> str:
    """A recommended maintenance window biased to a low-demand period."""
    days = max(0.0, round(time_to_intervention_days))
    return (
        f"Next low-demand window in ~{days:.0f} d "
        f"(overnight 02:00-06:00, off-peak product demand)"
    )


def pdm_for(asset_id: str, fouling: float = DEFAULT_FOULING) -> PdMRecommendation:
    """Assemble the preliminary PdM recommendation for one asset."""
    spec = _spec(asset_id)
    fp = failure_probability_for(asset_id, fouling)
    rul = rul_for(asset_id, fouling)
    priority = priority_for(asset_id, fouling)

    # Intervene ahead of the lower RUL bound so action precedes likely failure.
    time_to_intervention = round(max(0.0, min(rul.lower_days * 0.7, rul.rul_days * 0.5)), 1)

    return PdMRecommendation(
        asset_id=asset_id,
        asset_name=spec.name,
        predicted_failure_mode=spec.predicted_failure_mode,
        failure_probability_30d=fp.horizons["30d"],
        rul_days=rul.rul_days,
        rul_lower_days=rul.lower_days,
        rul_upper_days=rul.upper_days,
        time_to_intervention_days=time_to_intervention,
        recommended_window=_maintenance_window(time_to_intervention),
        spares_required=spec.spares_required,
        expected_downtime_hours=spec.expected_downtime_hours,
        maintenance_cost=spec.maintenance_cost,
        avoided_failure_cost=spec.avoided_failure_cost,
        rank_score=priority.rank_score,
        recommendation_id=f"rec-pdm-{asset_id.lower()}",
        control_boundary=ControlBoundary(),
        provenance=DataProvenance.preliminary,
    )


def compute_ranking(fouling: float = DEFAULT_FOULING) -> list[PdMRecommendation]:
    """Risk-ranked PdM recommendations across all assets (highest risk first)."""
    ranked = [pdm_for(asset_id, fouling) for asset_id in ASSETS]
    ranked.sort(key=lambda p: p.rank_score, reverse=True)
    return ranked


def compute_recommendations(fouling: float = DEFAULT_FOULING) -> list[PdMRecommendation]:
    """Alias for :func:`compute_ranking` (recommendations are risk-ranked)."""
    return compute_ranking(fouling)


def build_pdm_card(pdm: PdMRecommendation, fouling: float = DEFAULT_FOULING) -> RecommendationCard:
    """Build a canonical recommendation card from a PdM recommendation.

    The card is created ``pending`` with the read-only control boundary intact
    (operator approval required, no control write). Its id is derived from the
    asset so repeated polling is idempotent. The ranked root causes are attached
    as evidence so an operator can trace the recommendation.
    """
    rc = root_cause_for(pdm.asset_id)
    evidence = Evidence(
        telemetry_window="live synthetic equipment telemetry (preliminary)",
        assets_reviewed=[pdm.asset_id],
        documents_reviewed=[],
        simulation_ids=[],
        assumptions=[
            "Preliminary predictive-maintenance model (advisory, not validated).",
            "RUL, failure probability and avoided-cost are screening estimates "
            "with uncertainty, not guaranteed figures.",
        ],
        data_timestamp=now_iso(),
    )
    summary = (
        f"{pdm.asset_name}: predicted failure mode '{pdm.predicted_failure_mode}'; "
        f"30-day failure probability {pdm.failure_probability_30d:.0%}, "
        f"preliminary RUL {pdm.rul_days:.0f} d "
        f"({pdm.rul_lower_days:.0f}-{pdm.rul_upper_days:.0f} d)."
    )
    action = (
        f"Plan maintenance within ~{pdm.time_to_intervention_days:.0f} d. "
        f"{pdm.recommended_window}. Stage spares: "
        f"{', '.join(pdm.spares_required) if pdm.spares_required else 'none required'}. "
        f"Advisory only — operator approval required, no control write."
    )
    return RecommendationCard(
        recommendation_id=pdm.recommendation_id or f"rec-pdm-{uuid4().hex[:12]}",
        packet_id=f"pkt-pdm-{uuid4().hex[:12]}",
        facility_id=FACILITY_ID,
        train_id=TRAIN_ID,
        asset_id=pdm.asset_id,
        summary=summary,
        ranked_causes=rc.ranked_causes,
        recommended_action=action,
        confidence=round(pdm.failure_probability_30d, 3),
        evidence=evidence,
        control_boundary=ControlBoundary(),
        source_engine_status="predictive-maintenance: preliminary",
        created_at=now_iso(),
    )
