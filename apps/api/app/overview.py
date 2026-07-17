"""Plant-level command overview aggregation for Page 1."""

from __future__ import annotations

from statistics import mean

from .canonical_water_model import DataProvenance
from .synthetic import (
    ASSETS,
    FACILITY_ID,
    TRAIN_ID,
    anomaly_for,
    health_for,
    telemetry_metric,
)
from .store import list_recommendations
from .canonical_water_model import ApprovalStatus


def _metric_value(asset_id: str, metric: str, default: float = 0.0) -> float:
    r = telemetry_metric(asset_id, metric)
    return r.value if r else default


def build_overview() -> dict:
    healths = {a.asset_id: health_for(a.asset_id) for a in ASSETS}
    plant_health = round(mean(h.score for h in healths.values()), 1)

    permeate_flow = _metric_value("AST-MEMB-01", "permeate_flow_m3h", 498)
    feed_flow = _metric_value("AST-HPP-01", "flow_m3h", 505)
    recovery = _metric_value("AST-MEMB-01", "recovery_pct", 44)
    permeate_cond = _metric_value("AST-MEMB-01", "permeate_conductivity_us_cm", 285)

    total_power = sum(
        _metric_value(a.asset_id, "power_kw", 0.0) for a in ASSETS
    )
    # Specific energy: total electrical energy per m3 of product water.
    specific_energy = round(total_power / permeate_flow, 3) if permeate_flow else 0.0

    hp_health = healths.get("AST-HPP-01")
    memb_health = healths.get("AST-MEMB-01")
    hp_anomaly = anomaly_for("AST-HPP-01")

    recs = list_recommendations()
    active_recs = [r for r in recs if r.approval_status == ApprovalStatus.pending]

    # Alarms: derive from any asset in a poor band or high anomaly.
    alarms = []
    for a in ASSETS:
        h = healths[a.asset_id]
        an = anomaly_for(a.asset_id)
        if h.band.value in ("HighRisk", "Critical") or an.score >= 0.6:
            alarms.append(
                {
                    "asset_id": a.asset_id,
                    "asset_name": a.name,
                    "severity": "high" if an.score >= 0.6 else "medium",
                    "message": f"{a.name}: health {h.score} ({h.band.value}), anomaly {an.score}",
                    "provenance": DataProvenance.preliminary.value,
                }
            )

    # Service-continuity risk: worst-case combination of critical asset health
    # and pending advisories. Preliminary heuristic only.
    worst_critical = min(
        (healths[a.asset_id].score for a in ASSETS if a.criticality.value == "critical"),
        default=100.0,
    )
    risk_score = round(max(0.0, min(100.0, (100.0 - worst_critical) * 0.8 + len(alarms) * 4)), 1)
    if risk_score >= 60:
        risk_band = "high"
    elif risk_score >= 30:
        risk_band = "elevated"
    else:
        risk_band = "low"

    return {
        "facility_id": FACILITY_ID,
        "train_id": TRAIN_ID,
        "provenance": DataProvenance.preliminary.value,
        "plant_health": {
            "score": plant_health,
            "band": _band(plant_health),
            "provenance": DataProvenance.preliminary.value,
        },
        "production": {
            "permeate_flow_m3h": round(permeate_flow, 1),
            "product_m3_per_day": round(permeate_flow * 24, 0),
            "feed_flow_m3h": round(feed_flow, 1),
            "provenance": DataProvenance.synthetic.value,
        },
        "recovery_pct": {"value": round(recovery, 1), "provenance": DataProvenance.synthetic.value},
        "permeate_conductivity_us_cm": {
            "value": round(permeate_cond, 1),
            "provenance": DataProvenance.synthetic.value,
        },
        "energy": {
            "total_power_kw": round(total_power, 1),
            "specific_energy_kwh_m3": specific_energy,
            "provenance": DataProvenance.synthetic.value,
        },
        "hp_pump_status": {
            "asset_id": "AST-HPP-01",
            "health": hp_health.score if hp_health else None,
            "band": hp_health.band.value if hp_health else None,
            "anomaly": hp_anomaly.score,
            "provenance": DataProvenance.preliminary.value,
        },
        "membrane_status": {
            "asset_id": "AST-MEMB-01",
            "health": memb_health.score if memb_health else None,
            "band": memb_health.band.value if memb_health else None,
            "normalized_salt_passage_pct": _metric_value(
                "AST-MEMB-01", "normalized_salt_passage_pct", 1.8
            ),
            "provenance": DataProvenance.preliminary.value,
        },
        "active_alarms": alarms,
        "active_recommendations": [r.model_dump(mode="json") for r in active_recs],
        "service_continuity_risk": {
            "score": risk_score,
            "band": risk_band,
            "provenance": DataProvenance.preliminary.value,
        },
    }


def _band(score: float) -> str:
    if score >= 90:
        return "Healthy"
    if score >= 75:
        return "Monitor"
    if score >= 60:
        return "Degraded"
    if score >= 40:
        return "HighRisk"
    return "Critical"
