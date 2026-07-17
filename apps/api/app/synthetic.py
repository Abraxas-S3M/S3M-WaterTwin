"""Synthetic, provenance-tagged data generator for the reference API.

Everything produced here is flagged ``synthetic`` or ``preliminary`` so the
dashboard can render honest provenance badges. This module stands in for the
real Phase 6 services (health engine, anomaly engine, S3M recommendation
engine). It is deterministic per-asset with a small time-varying jitter so the
4-second polling in the UI shows live movement without being misleading.
"""

from __future__ import annotations

import math
import time
from typing import Optional

from .canonical_water_model import (
    AnomalyDomain,
    AnomalyResult,
    Asset,
    AssetType,
    Criticality,
    DataProvenance,
    HealthBand,
    HealthContribution,
    HealthScore,
    RatedData,
    StreamType,
    TelemetryReading,
    TreatmentStage,
    WaterStream,
    now_iso,
)

FACILITY_ID = "SWRO-ALPHA"
TRAIN_ID = "TRAIN-01"


def _asset(
    asset_id: str,
    name: str,
    asset_type: AssetType,
    stage: TreatmentStage,
    criticality: Criticality,
    rated: RatedData,
    manufacturer: str,
    model: str,
) -> Asset:
    return Asset(
        asset_id=asset_id,
        name=name,
        asset_type=asset_type,
        facility_id=FACILITY_ID,
        train_id=TRAIN_ID,
        treatment_stage=stage,
        manufacturer=manufacturer,
        model=model,
        serial_number=f"SN-{asset_id}",
        location=f"{FACILITY_ID}/{TRAIN_ID}/{stage.value}",
        criticality=criticality,
        rated=rated,
        install_date="2021-03-15",
    )


ASSETS: list[Asset] = [
    _asset(
        "AST-INTK-01",
        "Intake Pump A",
        AssetType.intake_pump,
        TreatmentStage.intake,
        Criticality.high,
        RatedData(
            rated_flow_m3h=1200,
            rated_head_m=35,
            rated_power_kw=160,
            rated_speed_rpm=1480,
            bep_flow_m3h=1100,
            min_flow_m3h=500,
            max_flow_m3h=1350,
            temp_limit_c=85,
            vibration_limit_mm_s=7.1,
        ),
        "Flowserve",
        "SWRO-INT-1200",
    ),
    _asset(
        "AST-CFLT-01",
        "Cartridge Filter Bank",
        AssetType.cartridge_filter,
        TreatmentStage.cartridge_filtration,
        Criticality.medium,
        RatedData(max_flow_m3h=1100),
        "Pentair",
        "CF-5um-XL",
    ),
    _asset(
        "AST-DOSE-01",
        "Antiscalant Dosing Pump",
        AssetType.dosing_pump,
        TreatmentStage.dosing,
        Criticality.medium,
        RatedData(rated_flow_m3h=0.8, rated_power_kw=1.1, vibration_limit_mm_s=4.5),
        "ProMinent",
        "Sigma-X",
    ),
    _asset(
        "AST-HPP-01",
        "High-Pressure Pump A",
        AssetType.hp_pump,
        TreatmentStage.high_pressure_pumping,
        Criticality.critical,
        RatedData(
            rated_flow_m3h=520,
            rated_head_m=680,
            rated_power_kw=1250,
            rated_speed_rpm=2980,
            bep_flow_m3h=500,
            min_flow_m3h=300,
            max_flow_m3h=560,
            temp_limit_c=90,
            vibration_limit_mm_s=4.5,
        ),
        "KSB",
        "Multitec-HP",
    ),
    _asset(
        "AST-ERD-01",
        "Energy Recovery Device",
        AssetType.erd,
        TreatmentStage.concentrate_discharge,
        Criticality.high,
        RatedData(rated_flow_m3h=430, rated_power_kw=0, max_flow_m3h=460),
        "Energy Recovery Inc",
        "PX-Q300",
    ),
    _asset(
        "AST-MEMB-01",
        "RO Membrane Array Stage 1",
        AssetType.membrane_array,
        TreatmentStage.ro_stage_1,
        Criticality.critical,
        RatedData(rated_flow_m3h=500, max_flow_m3h=520, temp_limit_c=45),
        "DuPont",
        "SW30HRLE-440",
    ),
    _asset(
        "AST-PERM-01",
        "Permeate Transfer Pump",
        AssetType.permeate_pump,
        TreatmentStage.permeate,
        Criticality.high,
        RatedData(
            rated_flow_m3h=310,
            rated_head_m=45,
            rated_power_kw=55,
            rated_speed_rpm=1480,
            bep_flow_m3h=300,
            min_flow_m3h=150,
            max_flow_m3h=340,
            temp_limit_c=80,
            vibration_limit_mm_s=7.1,
        ),
        "Grundfos",
        "NK-Perm",
    ),
    _asset(
        "AST-BRNE-01",
        "Brine Discharge Pump",
        AssetType.brine_pump,
        TreatmentStage.concentrate_discharge,
        Criticality.medium,
        RatedData(
            rated_flow_m3h=430,
            rated_head_m=25,
            rated_power_kw=45,
            bep_flow_m3h=410,
            min_flow_m3h=200,
            max_flow_m3h=470,
            temp_limit_c=80,
            vibration_limit_mm_s=7.1,
        ),
        "Xylem",
        "BR-430",
    ),
]

ASSET_INDEX: dict[str, Asset] = {a.asset_id: a for a in ASSETS}

STREAMS: list[WaterStream] = [
    WaterStream(
        stream_id="STR-01",
        stream_type=StreamType.seawater_feed,
        from_stage=TreatmentStage.intake,
        to_stage=TreatmentStage.cartridge_filtration,
        description="Raw seawater from intake to cartridge filtration",
    ),
    WaterStream(
        stream_id="STR-02",
        stream_type=StreamType.pretreated_feed,
        from_stage=TreatmentStage.cartridge_filtration,
        to_stage=TreatmentStage.dosing,
        description="Filtered feed to antiscalant dosing",
    ),
    WaterStream(
        stream_id="STR-03",
        stream_type=StreamType.ro_feed,
        from_stage=TreatmentStage.dosing,
        to_stage=TreatmentStage.high_pressure_pumping,
        description="Dosed feed to high-pressure pumping",
    ),
    WaterStream(
        stream_id="STR-04",
        stream_type=StreamType.ro_feed,
        from_stage=TreatmentStage.high_pressure_pumping,
        to_stage=TreatmentStage.ro_stage_1,
        description="High-pressure feed to RO membrane array",
    ),
    WaterStream(
        stream_id="STR-05",
        stream_type=StreamType.permeate,
        from_stage=TreatmentStage.ro_stage_1,
        to_stage=TreatmentStage.permeate,
        description="Permeate to transfer/product",
    ),
    WaterStream(
        stream_id="STR-06",
        stream_type=StreamType.product_water,
        from_stage=TreatmentStage.permeate,
        to_stage=TreatmentStage.distribution_handoff,
        description="Product water to distribution handoff",
    ),
    WaterStream(
        stream_id="STR-07",
        stream_type=StreamType.concentrate,
        from_stage=TreatmentStage.ro_stage_1,
        to_stage=TreatmentStage.concentrate_discharge,
        description="Concentrate to energy recovery device",
    ),
    WaterStream(
        stream_id="STR-08",
        stream_type=StreamType.concentrate,
        from_stage=TreatmentStage.concentrate_discharge,
        to_stage=TreatmentStage.concentrate_discharge,
        description="Brine from ERD to outfall discharge",
    ),
]


def _seed(asset_id: str) -> float:
    return (abs(hash(asset_id)) % 1000) / 1000.0


def _wave(asset_id: str, period_s: float = 45.0, phase: float = 0.0) -> float:
    """Deterministic time-varying value in [-1, 1]."""
    t = time.time()
    return math.sin((t / period_s) * 2 * math.pi + phase + _seed(asset_id) * 6.283)


# Baseline health scores (0-100) chosen so the plant shows a realistic spread
# of bands, including one degraded HP pump to make the demo meaningful.
_HEALTH_BASE: dict[str, float] = {
    "AST-INTK-01": 91.0,
    "AST-CFLT-01": 78.0,
    "AST-DOSE-01": 88.0,
    "AST-HPP-01": 63.0,
    "AST-ERD-01": 84.0,
    "AST-MEMB-01": 71.0,
    "AST-PERM-01": 93.0,
    "AST-BRNE-01": 86.0,
}


def health_for(asset_id: str) -> HealthScore:
    base = _HEALTH_BASE.get(asset_id, 82.0)
    score = max(0.0, min(100.0, base + _wave(asset_id, 120.0) * 2.5))
    contributions = _health_contributions(asset_id, score)
    return HealthScore(
        asset_id=asset_id,
        score=round(score, 1),
        band=HealthBand.from_score(score),
        contributions=contributions,
        provenance=DataProvenance.preliminary,
    )


def _health_contributions(asset_id: str, score: float) -> list[HealthContribution]:
    asset = ASSET_INDEX.get(asset_id)
    contribs: list[HealthContribution] = [
        HealthContribution(
            factor="Vibration trend",
            delta=round(-8.0 + _wave(asset_id, 90.0) * 3.0, 1),
            detail="RMS velocity vs rated limit over 14-day window",
        ),
        HealthContribution(
            factor="Bearing temperature",
            delta=round(-4.0 + _wave(asset_id, 70.0, 1.2) * 2.0, 1),
            detail="Drive-end bearing temperature margin",
        ),
        HealthContribution(
            factor="Efficiency drift",
            delta=round(-6.0 + _wave(asset_id, 150.0, 2.4) * 2.5, 1),
            detail="Hydraulic efficiency vs commissioning baseline",
        ),
        HealthContribution(
            factor="Runtime hours",
            delta=-3.5,
            detail="Cumulative runtime since last overhaul",
        ),
    ]
    if asset and asset.asset_type == AssetType.membrane_array:
        contribs.append(
            HealthContribution(
                factor="Normalized salt passage",
                delta=round(-9.0 + _wave(asset_id, 200.0) * 2.0, 1),
                detail="Salt passage rising vs first-year baseline (fouling)",
            )
        )
    return contribs


_ANOMALY_BASE: dict[str, float] = {
    "AST-INTK-01": 0.12,
    "AST-CFLT-01": 0.28,
    "AST-DOSE-01": 0.15,
    "AST-HPP-01": 0.61,
    "AST-ERD-01": 0.22,
    "AST-MEMB-01": 0.44,
    "AST-PERM-01": 0.08,
    "AST-BRNE-01": 0.18,
}


def anomaly_for(asset_id: str) -> AnomalyResult:
    base = _ANOMALY_BASE.get(asset_id, 0.2)
    score = max(0.0, min(1.0, base + _wave(asset_id, 60.0) * 0.05))
    asset = ASSET_INDEX.get(asset_id)
    if asset and asset.asset_type in (AssetType.hp_pump, AssetType.intake_pump, AssetType.permeate_pump):
        ranked = [
            (AnomalyDomain.mechanical, round(score * 0.9, 3)),
            (AnomalyDomain.hydraulic, round(score * 0.6, 3)),
            (AnomalyDomain.electrical, round(score * 0.3, 3)),
        ]
    elif asset and asset.asset_type == AssetType.membrane_array:
        ranked = [
            (AnomalyDomain.membrane, round(score * 0.95, 3)),
            (AnomalyDomain.water_quality, round(score * 0.55, 3)),
            (AnomalyDomain.process, round(score * 0.4, 3)),
        ]
    else:
        ranked = [
            (AnomalyDomain.process, round(score * 0.8, 3)),
            (AnomalyDomain.mechanical, round(score * 0.4, 3)),
        ]
    return AnomalyResult(
        asset_id=asset_id,
        score=round(score, 3),
        ranked_domains=ranked,
        factors={
            "vibration_rms": round(0.5 + _wave(asset_id, 40.0) * 0.2, 3),
            "temp_margin": round(0.3 + _wave(asset_id, 55.0, 1.0) * 0.15, 3),
            "efficiency": round(0.4 + _wave(asset_id, 80.0, 2.0) * 0.2, 3),
        },
        provenance=DataProvenance.preliminary,
    )


_METRICS_BY_TYPE: dict[AssetType, list[tuple[str, str, float, float]]] = {
    # metric, unit, base, amplitude
    AssetType.intake_pump: [
        ("flow_m3h", "m³/h", 1080, 40),
        ("suction_pressure_bar", "bar", 1.2, 0.15),
        ("discharge_pressure_bar", "bar", 3.4, 0.2),
        ("vibration_mm_s", "mm/s", 3.1, 0.8),
        ("bearing_temp_c", "°C", 58, 4),
        ("power_kw", "kW", 148, 8),
        ("speed_rpm", "rpm", 1470, 15),
    ],
    AssetType.hp_pump: [
        ("flow_m3h", "m³/h", 505, 20),
        ("suction_pressure_bar", "bar", 2.8, 0.2),
        ("discharge_pressure_bar", "bar", 66, 2.5),
        ("vibration_mm_s", "mm/s", 3.6, 1.1),
        ("bearing_temp_c", "°C", 71, 6),
        ("power_kw", "kW", 1180, 45),
        ("speed_rpm", "rpm", 2965, 25),
    ],
    AssetType.permeate_pump: [
        ("flow_m3h", "m³/h", 302, 15),
        ("discharge_pressure_bar", "bar", 4.3, 0.2),
        ("vibration_mm_s", "mm/s", 2.4, 0.6),
        ("bearing_temp_c", "°C", 52, 3),
        ("power_kw", "kW", 52, 4),
        ("speed_rpm", "rpm", 1472, 12),
    ],
    AssetType.brine_pump: [
        ("flow_m3h", "m³/h", 415, 18),
        ("discharge_pressure_bar", "bar", 2.4, 0.15),
        ("vibration_mm_s", "mm/s", 2.9, 0.7),
        ("bearing_temp_c", "°C", 49, 3),
        ("power_kw", "kW", 42, 3),
    ],
    AssetType.dosing_pump: [
        ("flow_lph", "L/h", 620, 30),
        ("stroke_pct", "%", 74, 6),
        ("power_kw", "kW", 0.9, 0.1),
    ],
    AssetType.membrane_array: [
        ("feed_pressure_bar", "bar", 64, 2),
        ("permeate_flow_m3h", "m³/h", 498, 12),
        ("permeate_conductivity_us_cm", "µS/cm", 285, 25),
        ("differential_pressure_bar", "bar", 1.6, 0.2),
        ("recovery_pct", "%", 44, 1.5),
        ("normalized_salt_passage_pct", "%", 1.8, 0.3),
    ],
    AssetType.erd: [
        ("feed_flow_m3h", "m³/h", 425, 15),
        ("transfer_efficiency_pct", "%", 96.5, 0.8),
        ("mixing_pct", "%", 4.2, 0.5),
        ("vibration_mm_s", "mm/s", 1.8, 0.4),
    ],
    AssetType.cartridge_filter: [
        ("differential_pressure_bar", "bar", 0.35, 0.08),
        ("flow_m3h", "m³/h", 1075, 35),
        ("turbidity_ntu", "NTU", 0.12, 0.03),
    ],
}


def telemetry_for(asset_id: str) -> list[TelemetryReading]:
    asset = ASSET_INDEX.get(asset_id)
    if asset is None:
        return []
    specs = _METRICS_BY_TYPE.get(asset.asset_type, [("status", "state", 1, 0)])
    ts = now_iso()
    readings: list[TelemetryReading] = []
    for i, (metric, unit, base, amp) in enumerate(specs):
        value = base + _wave(asset_id, 30.0 + i * 7, phase=i * 0.7) * amp
        readings.append(
            TelemetryReading(
                asset_id=asset_id,
                metric=metric,
                value=round(value, 3),
                unit=unit,
                timestamp=ts,
                provenance=DataProvenance.synthetic,
                quality="good",
            )
        )
    return readings


def telemetry_metric(asset_id: str, metric: str) -> Optional[TelemetryReading]:
    for r in telemetry_for(asset_id):
        if r.metric == metric:
            return r
    return None


def pump_curve(asset_id: str) -> dict:
    """Build a synthetic head/flow pump curve plus current operating point.

    Uses the rated point and BEP to shape a plausible quadratic H-Q curve. Marked
    synthetic; the real curve comes from manufacturer data in a later phase.
    """
    asset = ASSET_INDEX.get(asset_id)
    if asset is None or asset.rated.rated_head_m is None or asset.rated.bep_flow_m3h is None:
        return {"asset_id": asset_id, "supported": False, "provenance": DataProvenance.synthetic.value}

    h0 = asset.rated.rated_head_m * 1.25  # shutoff head
    q_bep = asset.rated.bep_flow_m3h
    h_bep = asset.rated.rated_head_m
    # H(Q) = h0 - k*Q^2 fitted through the BEP.
    k = (h0 - h_bep) / (q_bep ** 2) if q_bep else 0.0
    q_max = asset.rated.max_flow_m3h or q_bep * 1.15
    curve = []
    steps = 25
    for i in range(steps + 1):
        q = (q_max * 1.05) * i / steps
        h = max(0.0, h0 - k * q * q)
        eff = max(0.0, 100.0 * (1 - ((q - q_bep) / (q_bep + 1e-6)) ** 2 * 1.1))
        curve.append({"flow_m3h": round(q, 1), "head_m": round(h, 1), "efficiency_pct": round(eff, 1)})

    flow = telemetry_metric(asset_id, "flow_m3h")
    op_flow = flow.value if flow else q_bep * 0.98
    op_head = max(0.0, h0 - k * op_flow * op_flow)
    return {
        "asset_id": asset_id,
        "supported": True,
        "provenance": DataProvenance.synthetic.value,
        "bep": {"flow_m3h": round(q_bep, 1), "head_m": round(h_bep, 1)},
        "operating_point": {"flow_m3h": round(op_flow, 1), "head_m": round(op_head, 1)},
        "curve": curve,
    }
