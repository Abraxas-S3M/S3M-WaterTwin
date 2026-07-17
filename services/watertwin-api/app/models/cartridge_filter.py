"""D1 Model 3 -- cartridge-filter replacement (advisory, read-only).

Consumes cartridge-filter telemetry (differential pressure, flow, turbidity,
particle count, SDI, runtime and replacement history) and emits an explainable
**filter-health index**, a **replacement-due probability** and a preliminary
remaining runtime.

The model REUSES the canonical physics rather than re-deriving it:

* :func:`watertwin_engineering.component_health` (``"filter"``) for the
  transparent normalized-differential-pressure health index;
* :func:`watertwin_engineering.colloidal_fouling_index` for the SDI / turbidity /
  particle-count loading; and
* :func:`watertwin_engineering.remaining_useful_life_days` for the preliminary
  remaining runtime.

Everything is preliminary and advisory: outputs carry the read-only control
boundary and ``provenance = preliminary``; thresholds are preliminary pending
customer calibration.
"""

from __future__ import annotations

import math

from canonical_water_model import DataProvenance, Evidence, HealthContribution, now_iso
from watertwin_engineering import (
    colloidal_fouling_index,
    component_health,
    remaining_useful_life_days,
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

MODEL_ID = "d1-cartridge-filter"
MODEL_VERSION = "0.1.0-preliminary"
ASSET_ID = "AST-CF-01"

#: Cartridge change-out is typically at ~2.5x clean differential pressure
#: (documented screening ratio; the ``component_health('filter')`` model uses the
#: 2-3x band). The replacement probability is anchored here (not re-derived).
CHANGEOUT_NORMALIZED_DP = 2.5

#: Recommended cartridge replacement interval (days) for the RUL projection.
REPLACEMENT_INTERVAL_DAYS = 90.0

CLEAN_DP_BAR = 0.3


def _num(inputs: dict[str, float], key: str, default: float) -> float:
    value = inputs.get(key, default)
    return float(default if value is None else value)


def _normalized_dp(inputs: dict[str, float]) -> float:
    if inputs.get("normalized_dp") is not None:
        return float(inputs["normalized_dp"])
    clean = _num(inputs, "clean_dp_bar", CLEAN_DP_BAR)
    dp = _num(inputs, "dp_bar", clean)
    return dp / clean if clean > 0 else 1.0


def _loading(inputs: dict[str, float]) -> float:
    """Colloidal loading (0-1) from SDI / turbidity / particle count (reused)."""
    return colloidal_fouling_index(
        sdi=_num(inputs, "sdi", 0.0),
        turbidity_ntu=_num(inputs, "turbidity_ntu", 0.0),
        particle_count=_num(inputs, "particle_count_per_ml", 0.0),
    )


def _health(inputs: dict[str, float]):
    return component_health("filter", {"normalized_dp": _normalized_dp(inputs)})


def replacement_due_probability(inputs: dict[str, float]) -> float:
    """Preliminary replacement-due probability anchored on the change-out ratio.

    Logistic on the normalized differential pressure anchored so ``p = 0.5`` at
    the documented change-out ratio, nudged up by high colloidal loading.
    """
    ndp = _normalized_dp(inputs)
    base = 1.0 / (1.0 + math.exp(-(ndp - CHANGEOUT_NORMALIZED_DP) / 0.4))
    loading = _loading(inputs)
    prob = 0.8 * base + 0.2 * loading
    return round(min(1.0, max(0.0, prob)), 4)


def remaining_runtime_days(inputs: dict[str, float]):
    """Preliminary remaining runtime via the shared RUL engine.

    Synthesizes a short filter-health trend from the current health and a
    loading-driven decline rate, then reuses ``remaining_useful_life_days``.
    """
    health = _health(inputs)
    loading = _loading(inputs)
    daily_decline = 0.3 + 6.0 * loading
    trend = [min(100.0, health.score + daily_decline * k) for k in range(4, -1, -1)]
    return remaining_useful_life_days(
        health_trend=trend,
        duty_cycle=_num(inputs, "duty_cycle", 0.65),
        maintenance_age_days=_num(inputs, "days_since_replacement", 45.0),
        recommended_interval_days=REPLACEMENT_INTERVAL_DAYS,
        comparable_asset_factor=1.0,
        failure_threshold=45.0,
    )


def risk_score(features: dict[str, float]) -> float:
    """Probability the cartridge is due for replacement (back-test scalar)."""
    health = _health(features)
    unhealth = 1.0 - health.score / 100.0
    repl = replacement_due_probability(features)
    return round(min(1.0, max(0.0, 0.5 * unhealth + 0.5 * repl)), 4)


SPEC = ModelSpec(
    model_id=MODEL_ID,
    version=MODEL_VERSION,
    name="Cartridge-Filter Replacement (D1)",
    description=(
        "Filter-health index, replacement-due probability and preliminary "
        "remaining runtime from differential pressure, flow, turbidity, particle "
        "count, SDI, runtime and replacement history. Reuses the canonical "
        "filter-health, colloidal-fouling and RUL physics."
    ),
    asset_type="cartridge_filter",
    target="filter_health_index + replacement_due_probability",
    outputs=[
        "filter_health_index",
        "replacement_due_probability",
        "remaining_runtime_days",
        "health_band",
    ],
    inputs=[
        InputSignal(
            name="dp_bar", unit="bar", description="Differential pressure across the cartridge bank."
        ),
        InputSignal(
            name="clean_dp_bar",
            unit="bar",
            description="Clean (new-cartridge) differential pressure.",
            source="derived",
        ),
        InputSignal(name="flow_m3h", unit="m3/h", description="Throughput flow."),
        InputSignal(name="turbidity_ntu", unit="NTU", description="Upstream turbidity."),
        InputSignal(
            name="particle_count_per_ml", unit="count/mL", description="Upstream particle count."
        ),
        InputSignal(name="sdi", unit="index", description="Silt Density Index."),
        InputSignal(
            name="runtime_hours",
            unit="h",
            description="Cartridge runtime since install.",
            source="history",
        ),
        InputSignal(
            name="days_since_replacement",
            unit="days",
            description="Days since last replacement.",
            source="history",
        ),
    ],
    baseline=BaselineRef(
        name="new-cartridge",
        description="New-cartridge reference (normalized dP = 1.0, low loading).",
        reference_values={
            "normalized_dp": 1.0,
            "filter_health_index": 100.0,
            "changeout_normalized_dp": CHANGEOUT_NORMALIZED_DP,
        },
        source="synthetic reference cartridge bank (AST-CF-01)",
    ),
    thresholds=[
        AlertThreshold(
            name="Differential pressure change-out",
            metric="normalized_dp",
            direction=ThresholdDirection.above,
            value=CHANGEOUT_NORMALIZED_DP,
            severity="warning",
            rationale="Cartridge change-out at ~2.5x clean dP (preliminary).",
        ),
        AlertThreshold(
            name="SDI high",
            metric="sdi",
            direction=ThresholdDirection.above,
            value=5.0,
            severity="watch",
            rationale="Elevated SDI accelerates plugging (preliminary).",
        ),
        AlertThreshold(
            name="Replacement-due probability high",
            metric="replacement_due_probability",
            direction=ThresholdDirection.above,
            value=0.5,
            severity="warning",
            rationale="Screening trigger on the replacement probability (preliminary).",
        ),
        AlertThreshold(
            name="Filter health degraded",
            metric="filter_health_index",
            direction=ThresholdDirection.below,
            value=60.0,
            severity="warning",
            rationale="Degraded health band cutoff (preliminary).",
        ),
    ],
    reused_components=[
        ReusedComponent(
            name="component_health(filter)",
            module="watertwin_engineering.equipment",
            purpose="Normalized-dP filter-health index.",
        ),
        ReusedComponent(
            name="colloidal_fouling_index",
            module="watertwin_engineering.water_quality",
            purpose="SDI / turbidity / particle-count loading.",
        ),
        ReusedComponent(
            name="remaining_useful_life_days",
            module="watertwin_engineering.equipment",
            purpose="Preliminary remaining runtime projection.",
        ),
    ],
    drift=DriftConfig(
        features=["normalized_dp", "sdi", "turbidity_ntu", "particle_count_per_ml", "flow_m3h"]
    ),
    calibration=CalibrationConfig(),
    false_alarm=FalseAlarmConfig(),
    assumptions=[
        "Preliminary D1 model; thresholds pending customer calibration.",
        "Reuses canonical filter-health, colloidal-fouling and RUL physics.",
        "Advisory and read-only -- no control write.",
    ],
)


class _CartridgeFilterModel:
    """Adapter binding the cartridge-filter spec to its runtime behaviour."""

    spec = SPEC

    def assess(self, inputs: dict[str, float] | None = None) -> ModelAssessment:
        data = {**_BASELINE, **(inputs or {})}
        health = _health(data)
        ndp = _normalized_dp(data)
        repl = replacement_due_probability(data)
        rul = remaining_runtime_days(data)

        observed = {
            "normalized_dp": ndp,
            "sdi": _num(data, "sdi", 0.0),
            "replacement_due_probability": repl,
            "filter_health_index": health.score,
        }
        triggered = evaluate_thresholds(SPEC.thresholds, observed)

        evidence = Evidence(
            telemetry_window="latest synthetic cartridge-filter telemetry (preliminary)",
            assets_reviewed=[ASSET_ID],
            assumptions=SPEC.assumptions,
            data_timestamp=now_iso(),
        )
        return ModelAssessment(
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            asset_id=ASSET_ID,
            indices={
                "filter_health_index": health.score,
                "normalized_dp": round(ndp, 3),
                "remaining_runtime_days": rul.rul_days,
                "remaining_runtime_lower_days": rul.lower_days,
                "remaining_runtime_upper_days": rul.upper_days,
                "colloidal_loading": round(_loading(data), 4),
            },
            probabilities={"replacement_due_probability": repl},
            band=health.band,
            contributions=[
                HealthContribution(factor=c.factor, delta=c.delta, detail=c.detail)
                for c in health.contributions
            ],
            triggered_alerts=triggered,
            confidence=0.62,
            confidence_calibrated=SPEC.calibration.calibrated,
            evidence=evidence,
            provenance=DataProvenance.preliminary,
        )

    def risk_score(self, features: dict[str, float]) -> float:
        return risk_score({**_BASELINE, **features})

    def backtest_dataset(self) -> BackTestDataset:
        return _backtest_dataset()

    def drift_monitor(self) -> FeatureDriftMonitor:
        return _drift_monitor()

    def backtest(self, threshold: float | None = None) -> BackTestMetrics:
        thr = 0.5 if threshold is None else threshold
        return run_backtest(self.backtest_dataset(), self.risk_score, threshold=thr)

    def benchmark(self) -> BenchmarkResult:
        drift = self.drift_monitor().check({"normalized_dp": [1.0, 1.1, 1.05, 1.0, 1.2, 1.1]})
        return run_benchmark(
            self.backtest_dataset(),
            self.risk_score,
            threshold=0.5,
            drift=drift,
            notes=[
                "Reuses canonical filter-health, colloidal-fouling and RUL physics.",
                "Thresholds preliminary pending customer calibration.",
            ],
        )


_BASELINE: dict[str, float] = {
    "dp_bar": 0.3,
    "clean_dp_bar": CLEAN_DP_BAR,
    "flow_m3h": 500.0,
    "turbidity_ntu": 0.2,
    "particle_count_per_ml": 500.0,
    "sdi": 3.0,
    "runtime_hours": 720.0,
    "days_since_replacement": 30.0,
}


def _clean(**over: float) -> dict[str, float]:
    base = {"dp_bar": 0.3, "clean_dp_bar": CLEAN_DP_BAR, "turbidity_ntu": 0.2,
            "particle_count_per_ml": 500.0, "sdi": 3.0, "days_since_replacement": 20.0}
    base.update(over)
    return base


def _plugged(**over: float) -> dict[str, float]:
    base = {"dp_bar": 0.9, "clean_dp_bar": CLEAN_DP_BAR, "turbidity_ntu": 0.6,
            "particle_count_per_ml": 3000.0, "sdi": 5.5, "days_since_replacement": 85.0}
    base.update(over)
    return base


def _backtest_dataset() -> BackTestDataset:
    """Synthetic labelled cartridge back-test dataset (clean vs plugged)."""
    samples: list[LabeledSample] = []
    for i in range(10):
        samples.append(
            LabeledSample(_clean(dp_bar=0.30 + 0.02 * i, sdi=2.8 + 0.05 * i), label=False, note="clean")
        )
    for i in range(9):
        samples.append(
            LabeledSample(
                _plugged(dp_bar=0.80 + 0.03 * i, sdi=5.0 + 0.1 * i),
                label=True,
                lead_time_days=12.0 - i,
                note="plugged / change-out due",
            )
        )
    # Early-warning positive the preliminary model narrowly misses (a FN).
    samples.append(
        LabeledSample(_clean(dp_bar=0.62, sdi=4.8, days_since_replacement=70.0),
                      label=True, lead_time_days=18.0, note="early-warning positive")
    )
    return BackTestDataset(
        model_id=MODEL_ID,
        name="Cartridge-filter synthetic back-test",
        description="Clean vs plugged cartridge-bank scenarios (synthetic).",
        samples=samples,
    )


def _drift_monitor() -> FeatureDriftMonitor:
    ds = _backtest_dataset()
    clean = [s.features for s in ds.samples if not s.label]
    baseline = {"normalized_dp": [f["dp_bar"] / f["clean_dp_bar"] for f in clean]}
    return FeatureDriftMonitor(
        MODEL_ID,
        baseline,
        warn_psi=SPEC.drift.warn_psi,
        alert_psi=SPEC.drift.alert_psi,
    )


ADAPTER = _CartridgeFilterModel()
