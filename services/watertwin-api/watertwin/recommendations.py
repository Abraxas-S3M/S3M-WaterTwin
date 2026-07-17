"""Local engineering analysis for high-pressure pumps (HPP) on an RO train.

This module is the WaterTwin's *own* physics-informed reasoning. It is used both to
enrich packets sent to S3M-Core and as the source of truth for the graceful local
fallback when S3M-Core is unavailable (see :mod:`watertwin.s3m_connector`).

Everything here is advisory: it ranks likely causes and maps the leading cause to a
recommended *advisory* action. It never emits a control command.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from .schemas import Evidence, RankedCause

logger = logging.getLogger("watertwin.recommendations")

# Physical constants for water-service hydraulic calculations.
RHO_KG_M3 = 1000.0
GRAVITY_M_S2 = 9.81
BAR_TO_PA = 1.0e5
# Saturation vapour pressure of water near ambient service temperature (~25 C).
VAPOUR_PRESSURE_BAR = 0.032

# Advisory action mapped from the leading ranked cause.
_CAUSE_ACTIONS: dict[str, str] = {
    "cavitation": (
        "Advisory: raise suction pressure or reduce pump speed to restore NPSH margin; "
        "inspect suction strainer and confirm feed tank level. No control write performed."
    ),
    "bearing-mechanical": (
        "Advisory: schedule vibration analysis and bearing/lubrication inspection at next "
        "maintenance window; trend bearing temperature. No control write performed."
    ),
    "membrane-fouling": (
        "Advisory: plan a clean-in-place (CIP) of the RO membranes and review antiscalant "
        "dosing and feed pre-treatment. No control write performed."
    ),
    "efficiency-loss": (
        "Advisory: schedule a pump performance test; inspect impeller and wear-rings for "
        "erosion/clearance loss. No control write performed."
    ),
    "sensor-error": (
        "Advisory: validate and recalibrate suspect instrumentation before acting on the "
        "readings; cross-check with redundant sensors. No control write performed."
    ),
}

# Telemetry keys we expect for a full-quality HPP assessment.
_EXPECTED_KEYS: tuple[str, ...] = (
    "suction_pressure_bar",
    "discharge_pressure_bar",
    "flow_m3h",
    "motor_power_kw",
    "feed_conductivity_us_cm",
    "permeate_conductivity_us_cm",
    "feed_flow_m3h",
    "permeate_flow_m3h",
    "vibration_mm_s",
    "bearing_temp_c",
)


class HPPMetrics(BaseModel):
    """Derived hydraulic / process metrics for an HPP assessment."""

    head_m: float = 0.0
    hydraulic_power_kw: float = 0.0
    electrical_power_kw: float = 0.0
    wire_to_water_efficiency: float = 0.0
    cavitation_index: float = 0.0
    recovery: float = 0.0
    salt_passage: float = 0.0


class HPPAssessment(BaseModel):
    """Result of :func:`assess_hpp`: metrics, ranked causes, and an advisory action."""

    asset_id: str
    metrics: HPPMetrics
    ranked_causes: list[RankedCause] = Field(default_factory=list)
    top_cause: str = ""
    recommended_action: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: Evidence | None = None


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0:
        return default
    return numerator / denominator


def _asset_id_of(asset: Any) -> str:
    if isinstance(asset, dict):
        return str(asset.get("asset_id") or asset.get("id") or "unknown-hpp")
    return str(getattr(asset, "asset_id", None) or getattr(asset, "id", None) or "unknown-hpp")


def _asset_get(asset: Any, key: str, default: Any = None) -> Any:
    if isinstance(asset, dict):
        return asset.get(key, default)
    return getattr(asset, key, default)


def _compute_metrics(asset: Any, telemetry: dict[str, Any]) -> HPPMetrics:
    suction = _num(telemetry.get("suction_pressure_bar"))
    discharge = _num(telemetry.get("discharge_pressure_bar"))
    flow_m3h = _num(telemetry.get("flow_m3h"))
    electrical_kw = _num(telemetry.get("motor_power_kw"))

    dp_bar = discharge - suction
    head_m = _safe_div(dp_bar * BAR_TO_PA, RHO_KG_M3 * GRAVITY_M_S2)

    flow_m3s = flow_m3h / 3600.0
    hydraulic_w = RHO_KG_M3 * GRAVITY_M_S2 * flow_m3s * head_m
    hydraulic_kw = hydraulic_w / 1000.0
    efficiency = _safe_div(hydraulic_kw, electrical_kw)

    # NPSH-based cavitation index; fall back to a suction-margin estimate.
    npsh_required = _num(_asset_get(asset, "npsh_required_m"), 0.0)
    npsh_available = telemetry.get("npsh_available_m")
    if npsh_available is None:
        npsh_available_m = _safe_div(
            (suction - VAPOUR_PRESSURE_BAR) * BAR_TO_PA, RHO_KG_M3 * GRAVITY_M_S2
        )
    else:
        npsh_available_m = _num(npsh_available)
    cavitation_index = _safe_div(npsh_available_m, npsh_required, default=npsh_available_m)

    recovery = _safe_div(
        _num(telemetry.get("permeate_flow_m3h")),
        _num(telemetry.get("feed_flow_m3h")),
    )
    salt_passage = _safe_div(
        _num(telemetry.get("permeate_conductivity_us_cm")),
        _num(telemetry.get("feed_conductivity_us_cm")),
    )

    return HPPMetrics(
        head_m=round(head_m, 3),
        hydraulic_power_kw=round(hydraulic_kw, 3),
        electrical_power_kw=round(electrical_kw, 3),
        wire_to_water_efficiency=round(efficiency, 4),
        cavitation_index=round(cavitation_index, 3),
        recovery=round(recovery, 4),
        salt_passage=round(salt_passage, 4),
    )


def _rank_causes(
    asset: Any, telemetry: dict[str, Any], m: HPPMetrics
) -> list[tuple[str, float, list[str]]]:
    """Return raw (cause, weight, evidence) tuples before normalisation."""
    vibration = _num(telemetry.get("vibration_mm_s"))
    bearing_temp = _num(telemetry.get("bearing_temp_c"))
    suction = _num(telemetry.get("suction_pressure_bar"))
    discharge = _num(telemetry.get("discharge_pressure_bar"))
    flow_m3h = _num(telemetry.get("flow_m3h"))

    rated_efficiency = _num(_asset_get(asset, "rated_efficiency"), 0.80)

    scored: list[tuple[str, float, list[str]]] = []

    # --- sensor error: implausible / inconsistent readings ------------------
    sensor_ev: list[str] = []
    sensor_score = 0.0
    if discharge < suction:
        sensor_ev.append(
            f"discharge {discharge:.2f} bar below suction {suction:.2f} bar (implausible)"
        )
        sensor_score += 0.9
    if m.wire_to_water_efficiency > 1.0:
        sensor_ev.append(
            f"wire-to-water efficiency {m.wire_to_water_efficiency:.2f} exceeds 1.0"
        )
        sensor_score += 0.9
    if flow_m3h < 0 or suction < 0:
        sensor_ev.append("negative flow or suction pressure reported")
        sensor_score += 0.6
    if m.salt_passage > 1.0:
        sensor_ev.append(f"salt passage {m.salt_passage:.2f} exceeds 1.0 (impossible)")
        sensor_score += 0.5
    if sensor_score:
        scored.append(("sensor-error", min(sensor_score, 1.0), sensor_ev))

    # --- cavitation ---------------------------------------------------------
    cav_ev: list[str] = []
    cav_score = 0.0
    if 0.0 < m.cavitation_index < 1.3:
        cav_ev.append(
            f"cavitation index {m.cavitation_index:.2f} below safe margin (>=1.3)"
        )
        cav_score += (1.3 - m.cavitation_index) / 1.3
    if suction and suction < 1.0:
        cav_ev.append(f"low suction pressure {suction:.2f} bar")
        cav_score += 0.3
    if vibration > 4.5 and 0.0 < m.cavitation_index < 1.5:
        cav_ev.append(
            f"elevated vibration {vibration:.1f} mm/s with low NPSH margin"
        )
        cav_score += 0.3
    if cav_score:
        scored.append(("cavitation", min(cav_score, 1.0), cav_ev))

    # --- bearing / mechanical ----------------------------------------------
    bear_ev: list[str] = []
    bear_score = 0.0
    if vibration > 4.5:
        bear_ev.append(f"vibration {vibration:.1f} mm/s above ISO 10816 alarm (4.5 mm/s)")
        bear_score += min((vibration - 4.5) / 6.0, 0.6) + 0.2
    if bearing_temp > 80.0:
        bear_ev.append(f"bearing temperature {bearing_temp:.1f} C above 80 C limit")
        bear_score += min((bearing_temp - 80.0) / 40.0, 0.5) + 0.2
    if bear_score:
        scored.append(("bearing-mechanical", min(bear_score, 1.0), bear_ev))

    # --- membrane fouling ---------------------------------------------------
    foul_ev: list[str] = []
    foul_score = 0.0
    if 0.0 < m.salt_passage <= 1.0 and m.salt_passage > 0.03:
        foul_ev.append(
            f"salt passage {m.salt_passage * 100:.1f}% above ~3% design target"
        )
        foul_score += min((m.salt_passage - 0.03) / 0.10, 0.6)
    if 0.0 < m.recovery < 0.35:
        foul_ev.append(f"recovery {m.recovery * 100:.1f}% below expected (>=35%)")
        foul_score += 0.4
    if foul_score:
        scored.append(("membrane-fouling", min(foul_score, 1.0), foul_ev))

    # --- efficiency loss ----------------------------------------------------
    eff_ev: list[str] = []
    eff_score = 0.0
    if 0.0 < m.wire_to_water_efficiency <= 1.0 and m.wire_to_water_efficiency < rated_efficiency:
        deficit = rated_efficiency - m.wire_to_water_efficiency
        eff_ev.append(
            f"wire-to-water efficiency {m.wire_to_water_efficiency * 100:.1f}% below "
            f"rated {rated_efficiency * 100:.1f}%"
        )
        eff_score += min(deficit / max(rated_efficiency, 0.01), 0.8)
    if eff_score:
        scored.append(("efficiency-loss", min(eff_score, 1.0), eff_ev))

    return scored


def _data_quality(telemetry: dict[str, Any]) -> float:
    present = sum(1 for k in _EXPECTED_KEYS if telemetry.get(k) is not None)
    return present / len(_EXPECTED_KEYS)


def assess_hpp(asset: Any, telemetry: dict[str, Any]) -> HPPAssessment:
    """Assess a high-pressure pump from telemetry and return ranked causes.

    Computes head, hydraulic power, wire-to-water efficiency, cavitation index,
    recovery and salt passage; derives ranked probable causes with evidence; and
    maps the leading cause to a recommended advisory action with a confidence score.
    """
    telemetry = telemetry or {}
    asset_id = _asset_id_of(asset)
    metrics = _compute_metrics(asset, telemetry)
    scored = _rank_causes(asset, telemetry, metrics)

    if not scored:
        # Nothing tripped a threshold: report a nominal, low-probability baseline
        # so downstream consumers always receive a non-empty ranking.
        scored = [(
            "efficiency-loss",
            0.05,
            ["no threshold exceeded; nominal operation within monitored bounds"],
        )]

    total = sum(weight for _, weight, _ in scored)
    ranked = [
        RankedCause(
            cause=cause,
            probability=round(_safe_div(weight, total, default=0.0), 4),
            evidence=evidence,
        )
        for cause, weight, evidence in scored
    ]
    ranked.sort(key=lambda rc: rc.probability, reverse=True)

    top = ranked[0]
    recommended_action = _CAUSE_ACTIONS.get(top.cause, _CAUSE_ACTIONS["sensor-error"])
    confidence = round(top.probability * _data_quality(telemetry), 4)

    evidence = build_evidence(
        asset_id=asset_id,
        telemetry=telemetry,
        metrics=metrics,
        assumptions=[
            f"water density {RHO_KG_M3:.0f} kg/m^3",
            f"gravity {GRAVITY_M_S2} m/s^2",
            f"vapour pressure {VAPOUR_PRESSURE_BAR} bar at service temperature",
        ],
    )

    return HPPAssessment(
        asset_id=asset_id,
        metrics=metrics,
        ranked_causes=ranked,
        top_cause=top.cause,
        recommended_action=recommended_action,
        confidence=confidence,
        evidence=evidence,
    )


def build_evidence(
    *,
    asset_id: str,
    telemetry: dict[str, Any],
    metrics: HPPMetrics | None = None,
    docs_reviewed: list[str] | None = None,
    simulation_ids: list[str] | None = None,
    assumptions: list[str] | None = None,
) -> Evidence:
    """Assemble the provenance :class:`Evidence` for an assessment."""
    data_ts_raw = telemetry.get("ts") if telemetry else None
    if isinstance(data_ts_raw, datetime):
        data_timestamp = data_ts_raw
    elif isinstance(data_ts_raw, str):
        try:
            data_timestamp = datetime.fromisoformat(data_ts_raw)
        except ValueError:
            data_timestamp = datetime.now(UTC)
    else:
        data_timestamp = datetime.now(UTC)

    telemetry_window: dict[str, Any] = {
        "sample_keys": sorted(telemetry.keys()) if telemetry else [],
        "sample_count": len(telemetry) if telemetry else 0,
    }
    if metrics is not None:
        telemetry_window["derived_metrics"] = metrics.model_dump()

    return Evidence(
        telemetry_window=telemetry_window,
        assets_reviewed=[asset_id],
        docs_reviewed=docs_reviewed
        or [
            "RO train HPP operating manual",
            "ISO 10816 vibration severity guide",
        ],
        simulation_ids=simulation_ids or [],
        assumptions=assumptions or [],
        data_timestamp=data_timestamp,
    )
