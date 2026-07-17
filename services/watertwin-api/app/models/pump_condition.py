"""D1 Model 1 -- HP-pump condition (advisory, read-only).

Consumes high-pressure-pump telemetry (suction/discharge pressure, flow, speed,
power, vibration, bearing temperature, seal leakage, pump-curve efficiency
deviation and the NPSH margin) and emits an **explainable pump-health index** plus
a **cavitation probability**.

The model does **not** re-derive any pump hydraulics or NPSH logic. It REUSES the
single canonical physics engine:

* :func:`watertwin_engineering.component_health` (``"pump"``) for the transparent
  visible-penalty health index (vibration / bearing / seal / efficiency drift);
* :func:`watertwin_engineering.operating_envelope_score` for the NPSH-margin /
  cavitation screening (its documented 0.5 m NPSH margin rule); and
* :func:`watertwin_engineering.root_cause_rank` for the pump-curve-deviation
  explainability.

Everything is preliminary and advisory: the output carries the read-only control
boundary and ``provenance = preliminary``, and every alert threshold is
preliminary pending customer calibration.
"""

from __future__ import annotations

import math

from canonical_water_model import DataProvenance, Evidence, HealthContribution, RankedCause, now_iso
from watertwin_engineering import (
    component_health,
    operating_envelope_score,
    root_cause_rank,
)
from watertwin_models import (
    AlertThreshold,
    BackTestDataset,
    BackTestMetrics,
    BaselineRef,
    BenchmarkResult,
    CalibrationConfig,
    DriftConfig,
    FalseAlarmConfig,
    FeatureDriftMonitor,
    InputSignal,
    LabeledSample,
    ModelSpec,
    ReusedComponent,
    ThresholdDirection,
)

from .base import ModelAssessment, evaluate_thresholds, run_backtest, run_benchmark

MODEL_ID = "d1-hp-pump-condition"
MODEL_VERSION = "0.1.0-preliminary"
ASSET_ID = "AST-HPP-01"

#: Documented NPSH margin (m) below which cavitation risk is asserted. This is
#: the SAME margin used inside ``operating_envelope_score``; it is referenced
#: here (not re-derived) so the cavitation probability is anchored to the
#: canonical rule.
NPSH_MARGIN_RULE_M = 0.5

#: Reference (healthy) HP-pump operating point used as the model baseline.
BASELINE_INPUTS: dict[str, float] = {
    "suction_pressure_bar": 2.5,
    "discharge_pressure_bar": 62.0,
    "flow_m3h": 500.0,
    "bep_flow_m3h": 500.0,
    "max_pressure_bar": 70.0,
    "speed_rpm": 2950.0,
    "power_kw": 900.0,
    "vibration_mm_s": 2.2,
    "vibration_limit_mm_s": 4.5,
    "bearing_temp_c": 68.0,
    "bearing_temp_limit_c": 90.0,
    "seal_leakage_ml_min": 1.0,
    "seal_leakage_limit_ml_min": 5.0,
    "pump_curve_efficiency_deviation_pct": 0.0,
    "temperature_c": 34.0,
    "temp_limit_c": 45.0,
    "npsh_available_m": 6.0,
    "npsh_required_m": 3.0,
}


def _num(inputs: dict[str, float], key: str, default: float) -> float:
    value = inputs.get(key, default)
    return float(default if value is None else value)


def _npsh_margin(inputs: dict[str, float]) -> float:
    """NPSH margin (m). Reuses the energy layer's ``available - required`` form."""
    if inputs.get("npsh_margin_m") is not None:
        return float(inputs["npsh_margin_m"])
    npsh_a = _num(inputs, "npsh_available_m", BASELINE_INPUTS["npsh_available_m"])
    npsh_r = _num(inputs, "npsh_required_m", BASELINE_INPUTS["npsh_required_m"])
    return npsh_a - npsh_r


def _pump_telemetry(inputs: dict[str, float]) -> dict[str, float]:
    """Map model inputs onto the canonical ``component_health('pump')`` signals.

    Pump-curve efficiency deviation is fed as the health engine's efficiency-drift
    term so curve deviation lowers the health index through the EXISTING penalty
    (no new hydraulic math here).
    """
    return {
        "vibration_mm_s": _num(inputs, "vibration_mm_s", BASELINE_INPUTS["vibration_mm_s"]),
        "vibration_limit_mm_s": _num(inputs, "vibration_limit_mm_s", 4.5),
        "bearing_temp_c": _num(inputs, "bearing_temp_c", BASELINE_INPUTS["bearing_temp_c"]),
        "bearing_temp_limit_c": _num(inputs, "bearing_temp_limit_c", 90.0),
        "seal_leakage_ml_min": _num(inputs, "seal_leakage_ml_min", 0.0),
        "seal_leakage_limit_ml_min": _num(inputs, "seal_leakage_limit_ml_min", 5.0),
        "efficiency_drift_pct": _num(inputs, "pump_curve_efficiency_deviation_pct", 0.0),
        "current_imbalance_pct": _num(inputs, "current_imbalance_pct", 0.0),
        "winding_temp_c": _num(inputs, "winding_temp_c", 0.0),
    }


def _envelope_sample(inputs: dict[str, float]) -> dict[str, float]:
    """One operating-envelope sample for ``operating_envelope_score`` reuse."""
    return {
        "flow_m3h": _num(inputs, "flow_m3h", BASELINE_INPUTS["flow_m3h"]),
        "bep_flow_m3h": _num(inputs, "bep_flow_m3h", BASELINE_INPUTS["bep_flow_m3h"]),
        "pressure_bar": _num(inputs, "discharge_pressure_bar", BASELINE_INPUTS["discharge_pressure_bar"]),
        "max_pressure_bar": _num(inputs, "max_pressure_bar", BASELINE_INPUTS["max_pressure_bar"]),
        "temperature_c": _num(inputs, "temperature_c", BASELINE_INPUTS["temperature_c"]),
        "temp_limit_c": _num(inputs, "temp_limit_c", BASELINE_INPUTS["temp_limit_c"]),
        "npsh_available_m": _num(inputs, "npsh_available_m", BASELINE_INPUTS["npsh_available_m"]),
        "npsh_required_m": _num(inputs, "npsh_required_m", BASELINE_INPUTS["npsh_required_m"]),
    }


def cavitation_probability(inputs: dict[str, float]) -> float:
    """Preliminary cavitation probability from the reused NPSH/cavitation logic.

    Blends the historical cavitation exposure (the ``cavitation_risk_fraction``
    from :func:`operating_envelope_score`, which encodes the documented 0.5 m NPSH
    margin rule) with a smooth logistic of the instantaneous NPSH margin anchored
    on the SAME 0.5 m boundary. No NPSH logic is duplicated.
    """
    env = operating_envelope_score([_envelope_sample(inputs)])
    margin = _npsh_margin(inputs)
    # Logistic anchored so p = 0.5 exactly at the documented margin rule.
    p_margin = 1.0 / (1.0 + math.exp((margin - NPSH_MARGIN_RULE_M) / 0.6))
    prob = 0.6 * p_margin + 0.4 * env.cavitation_risk_fraction
    return round(min(1.0, max(0.0, prob)), 4)


def _health_index(inputs: dict[str, float]):
    return component_health("pump", _pump_telemetry(inputs))


def risk_score(features: dict[str, float]) -> float:
    """Probability the pump is in a needs-attention condition (back-test scalar).

    Blends the reused pump-health deficit with the cavitation probability.
    """
    health = _health_index(features)
    unhealth = 1.0 - health.score / 100.0
    cav = cavitation_probability(features)
    return round(min(1.0, max(0.0, 0.6 * unhealth + 0.4 * cav)), 4)


def _confidence(inputs: dict[str, float]) -> float:
    """Preliminary confidence: higher when the key NPSH/vibration signals exist."""
    required = ("vibration_mm_s", "bearing_temp_c", "npsh_available_m", "npsh_required_m")
    present = sum(1 for k in required if inputs.get(k) is not None)
    return round(0.55 + 0.1 * present, 4)


SPEC = ModelSpec(
    model_id=MODEL_ID,
    version=MODEL_VERSION,
    name="HP-Pump Condition (D1)",
    description=(
        "Explainable high-pressure-pump health index and cavitation probability "
        "from vibration, bearing temperature, seal leakage, pump-curve efficiency "
        "deviation and the NPSH margin. Reuses the canonical component-health, "
        "operating-envelope (NPSH/cavitation) and root-cause physics."
    ),
    asset_type="hp_pump",
    target="pump_health_index + cavitation_probability",
    outputs=["pump_health_index", "cavitation_probability", "health_band", "ranked_causes"],
    inputs=[
        InputSignal(name="suction_pressure_bar", unit="bar", description="Pump suction pressure."),
        InputSignal(name="discharge_pressure_bar", unit="bar", description="Pump discharge pressure."),
        InputSignal(name="flow_m3h", unit="m3/h", description="Pump flow rate."),
        InputSignal(name="speed_rpm", unit="rpm", description="Pump/motor shaft speed."),
        InputSignal(name="power_kw", unit="kW", description="Electrical power draw."),
        InputSignal(name="vibration_mm_s", unit="mm/s", description="RMS vibration (ISO 10816)."),
        InputSignal(name="bearing_temp_c", unit="degC", description="Bearing temperature."),
        InputSignal(name="seal_leakage_ml_min", unit="mL/min", description="Mechanical-seal leakage."),
        InputSignal(
            name="pump_curve_efficiency_deviation_pct",
            unit="%",
            description="Operating point below the pump efficiency curve.",
            source="derived",
        ),
        InputSignal(
            name="npsh_margin_m",
            unit="m",
            description="NPSH available minus required (cavitation margin).",
            source="derived",
        ),
    ],
    baseline=BaselineRef(
        name="healthy-hp-pump",
        description="Reference healthy HP-pump operating point (clean, at BEP).",
        reference_values={
            "vibration_mm_s": BASELINE_INPUTS["vibration_mm_s"],
            "bearing_temp_c": BASELINE_INPUTS["bearing_temp_c"],
            "npsh_margin_m": BASELINE_INPUTS["npsh_available_m"] - BASELINE_INPUTS["npsh_required_m"],
            "pump_health_index": 100.0,
        },
        source="synthetic reference operating point (AST-HPP-01)",
    ),
    thresholds=[
        AlertThreshold(
            name="Vibration high",
            metric="vibration_mm_s",
            direction=ThresholdDirection.above,
            value=4.5,
            severity="warning",
            rationale="ISO 10816 zone C/D guidance for medium machines (preliminary).",
        ),
        AlertThreshold(
            name="Bearing temperature high",
            metric="bearing_temp_c",
            direction=ThresholdDirection.above,
            value=90.0,
            severity="warning",
            rationale="Typical bearing alarm limit (preliminary).",
        ),
        AlertThreshold(
            name="Seal leakage high",
            metric="seal_leakage_ml_min",
            direction=ThresholdDirection.above,
            value=5.0,
            severity="warning",
            rationale="Mechanical-seal leakage screening limit (preliminary).",
        ),
        AlertThreshold(
            name="NPSH margin low (cavitation)",
            metric="npsh_margin_m",
            direction=ThresholdDirection.below,
            value=NPSH_MARGIN_RULE_M,
            severity="critical",
            rationale="Reuses the canonical 0.5 m NPSH margin cavitation rule (preliminary).",
        ),
        AlertThreshold(
            name="Cavitation probability high",
            metric="cavitation_probability",
            direction=ThresholdDirection.above,
            value=0.5,
            severity="warning",
            rationale="Screening trigger on the reused NPSH-based probability (preliminary).",
        ),
        AlertThreshold(
            name="Pump health degraded",
            metric="pump_health_index",
            direction=ThresholdDirection.below,
            value=60.0,
            severity="warning",
            rationale="Degraded health band cutoff (preliminary).",
        ),
    ],
    reused_components=[
        ReusedComponent(
            name="component_health(pump)",
            module="watertwin_engineering.equipment",
            purpose="Explainable visible-penalty pump-health index.",
        ),
        ReusedComponent(
            name="operating_envelope_score",
            module="watertwin_engineering.equipment",
            purpose="NPSH margin / cavitation screening (0.5 m documented rule).",
        ),
        ReusedComponent(
            name="root_cause_rank",
            module="watertwin_engineering.root_cause",
            purpose="Pump-curve-deviation causal explainability.",
        ),
    ],
    drift=DriftConfig(
        features=[
            "vibration_mm_s",
            "bearing_temp_c",
            "power_kw",
            "flow_m3h",
            "npsh_margin_m",
            "discharge_pressure_bar",
        ]
    ),
    calibration=CalibrationConfig(),
    false_alarm=FalseAlarmConfig(),
    assumptions=[
        "Preliminary D1 model; thresholds pending customer calibration.",
        "Cavitation probability reuses the canonical NPSH/cavitation logic; not duplicated.",
        "Advisory and read-only -- no control write.",
    ],
)


class _PumpConditionModel:
    """Adapter binding the HP-pump condition spec to its runtime behaviour."""

    spec = SPEC

    def assess(self, inputs: dict[str, float] | None = None) -> ModelAssessment:
        data = {**BASELINE_INPUTS, **(inputs or {})}
        health = _health_index(data)
        cav = cavitation_probability(data)
        margin = _npsh_margin(data)

        ranked = root_cause_rank(
            {"asset_id": ASSET_ID, "asset_type": "pump"},
            {"power_pct_change": 0.0, "production_pct_change": 0.0},
            {
                "pump_curve_efficiency_deviation_pct": _num(
                    data, "pump_curve_efficiency_deviation_pct", 0.0
                ),
                "sensor_consistency": _num(data, "sensor_consistency", 1.0),
            },
        )

        observed = {
            "vibration_mm_s": _num(data, "vibration_mm_s", 0.0),
            "bearing_temp_c": _num(data, "bearing_temp_c", 0.0),
            "seal_leakage_ml_min": _num(data, "seal_leakage_ml_min", 0.0),
            "npsh_margin_m": margin,
            "cavitation_probability": cav,
            "pump_health_index": health.score,
        }
        triggered = evaluate_thresholds(SPEC.thresholds, observed)

        evidence = Evidence(
            telemetry_window="latest synthetic HP-pump telemetry (preliminary)",
            assets_reviewed=[ASSET_ID],
            assumptions=SPEC.assumptions,
            data_timestamp=now_iso(),
        )
        return ModelAssessment(
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            asset_id=ASSET_ID,
            indices={"pump_health_index": health.score, "npsh_margin_m": round(margin, 3)},
            probabilities={"cavitation_probability": cav},
            band=health.band,
            contributions=[
                HealthContribution(factor=c.factor, delta=c.delta, detail=c.detail)
                for c in health.contributions
            ],
            ranked_causes=[
                RankedCause(cause=rc.label, probability=rc.probability, evidence=rc.evidence)
                for rc in ranked
            ],
            triggered_alerts=triggered,
            confidence=_confidence(inputs or {}),
            confidence_calibrated=SPEC.calibration.calibrated,
            evidence=evidence,
            provenance=DataProvenance.preliminary,
        )

    def risk_score(self, features: dict[str, float]) -> float:
        return risk_score({**BASELINE_INPUTS, **features})

    def backtest_dataset(self) -> BackTestDataset:
        return _backtest_dataset()

    def drift_monitor(self) -> FeatureDriftMonitor:
        return _drift_monitor()

    def backtest(self, threshold: float | None = None) -> BackTestMetrics:
        thr = 0.5 if threshold is None else threshold
        return run_backtest(self.backtest_dataset(), self.risk_score, threshold=thr)

    def benchmark(self) -> BenchmarkResult:
        drift = self.drift_monitor().check(
            {
                "vibration_mm_s": [2.0, 2.2, 2.4, 2.1, 2.3, 2.0],
                "npsh_margin_m": [3.0, 2.9, 3.1, 3.0, 2.8, 3.0],
            }
        )
        return run_benchmark(
            self.backtest_dataset(),
            self.risk_score,
            threshold=0.5,
            drift=drift,
            notes=[
                "Reuses canonical NPSH/pump-curve/component-health physics.",
                "Thresholds preliminary pending customer calibration.",
            ],
        )


def _healthy(**over: float) -> dict[str, float]:
    base = {
        "vibration_mm_s": 2.2,
        "bearing_temp_c": 68.0,
        "seal_leakage_ml_min": 1.0,
        "pump_curve_efficiency_deviation_pct": 0.0,
        "npsh_available_m": 6.0,
        "npsh_required_m": 3.0,
    }
    base.update(over)
    return base


def _degraded(**over: float) -> dict[str, float]:
    base = {
        "vibration_mm_s": 7.0,
        "bearing_temp_c": 95.0,
        "seal_leakage_ml_min": 8.0,
        "pump_curve_efficiency_deviation_pct": 8.0,
        "npsh_available_m": 3.2,
        "npsh_required_m": 3.0,
    }
    base.update(over)
    return base


def _backtest_dataset() -> BackTestDataset:
    """Synthetic labelled HP-pump back-test dataset (healthy vs degraded)."""
    samples: list[LabeledSample] = []
    # Healthy population (label False).
    for i in range(10):
        samples.append(
            LabeledSample(
                _healthy(
                    vibration_mm_s=2.0 + 0.1 * i,
                    bearing_temp_c=66.0 + i,
                    npsh_available_m=6.0 - 0.1 * i,
                ),
                label=False,
                note="healthy operating point",
            )
        )
    # A borderline-healthy unit (just over the vibration alarm but not failing).
    samples.append(LabeledSample(_healthy(vibration_mm_s=4.6), label=False, note="watch"))
    # Degraded / cavitating population (label True) with detection lead times.
    for i in range(9):
        samples.append(
            LabeledSample(
                _degraded(
                    vibration_mm_s=6.5 + 0.2 * i,
                    bearing_temp_c=92.0 + i,
                    npsh_available_m=3.4 - 0.05 * i,
                ),
                label=True,
                lead_time_days=15.0 - i,
                note="degraded / cavitation risk",
            )
        )
    # An early-warning positive the preliminary model narrowly misses (a FN).
    samples.append(
        LabeledSample(
            _healthy(vibration_mm_s=5.2, bearing_temp_c=88.0, npsh_available_m=4.2),
            label=True,
            lead_time_days=25.0,
            note="early-warning positive",
        )
    )
    return BackTestDataset(
        model_id=MODEL_ID,
        name="HP-pump condition synthetic back-test",
        description="Healthy vs degraded/cavitating HP-pump operating points (synthetic).",
        samples=samples,
    )


def _drift_monitor() -> FeatureDriftMonitor:
    ds = _backtest_dataset()
    healthy = [s.features for s in ds.samples if not s.label]
    baseline = {
        "vibration_mm_s": [f["vibration_mm_s"] for f in healthy],
        "npsh_margin_m": [f["npsh_available_m"] - f["npsh_required_m"] for f in healthy],
    }
    return FeatureDriftMonitor(
        MODEL_ID,
        baseline,
        warn_psi=SPEC.drift.warn_psi,
        alert_psi=SPEC.drift.alert_psi,
    )


ADAPTER = _PumpConditionModel()
