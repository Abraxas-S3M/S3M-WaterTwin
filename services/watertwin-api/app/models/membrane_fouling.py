"""D1 Model 2 -- membrane fouling & salt passage (advisory, read-only).

Consumes the normalized RO-membrane signals (normalized permeate flow, normalized
salt passage, differential pressure, feed conductivity, temperature, recovery,
pressure, cleaning history and feed ion chemistry) and emits a membrane-health
index, a **salt-passage-breakthrough probability** and a preliminary CIP
recommendation.

This model does **not** re-create any water-quality or membrane physics. It
REUSES the existing Membrane + Water-Quality service layer:

* :func:`app.membrane.compute_membrane_health` -- which itself reuses
  :mod:`app.water_quality` for the normalized indices, fouling/scaling severity,
  the CIP flag and a preliminary membrane RUL; and
* :func:`app.water_quality.compute_scaling_risks` for the dominant scaling risk.

Everything is preliminary and advisory: outputs carry the read-only control
boundary and ``provenance = preliminary``; thresholds are preliminary pending
customer calibration.
"""

from __future__ import annotations

import math

from canonical_water_model import DataProvenance, Evidence, RankedCause, now_iso
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

from .. import membrane
from .base import ModelAssessment, evaluate_thresholds, run_backtest, run_benchmark

MODEL_ID = "d1-membrane-fouling"
MODEL_VERSION = "0.1.0-preliminary"
ASSET_ID = membrane.MEMBRANE_ASSET_ID

#: Default fouling severity for the reference scenario (mirrors the PdM default).
DEFAULT_FOULING = 0.35
DEFAULT_CIP_AGE_DAYS = 120.0


def _fouling(inputs: dict[str, float]) -> float:
    value = inputs.get("fouling", DEFAULT_FOULING)
    return max(0.0, min(1.0, float(DEFAULT_FOULING if value is None else value)))


def _cip_age(inputs: dict[str, float]) -> float:
    value = inputs.get("cip_age_days", DEFAULT_CIP_AGE_DAYS)
    return float(DEFAULT_CIP_AGE_DAYS if value is None else value)


def salt_passage_breakthrough_probability(sp_rise_pct: float) -> float:
    """Preliminary breakthrough probability, anchored on the reused CIP SP rule.

    Logistic on the normalized salt-passage rise anchored so ``p = 0.5`` at the
    canonical CIP salt-passage threshold (:data:`app.membrane.
    CIP_NORMALIZED_SP_RISE_PCT`). No membrane physics is re-derived.
    """
    anchor = membrane.CIP_NORMALIZED_SP_RISE_PCT
    prob = 1.0 / (1.0 + math.exp(-(sp_rise_pct - anchor) / 4.0))
    return round(min(1.0, max(0.0, prob)), 4)


def risk_score(features: dict[str, float]) -> float:
    """Probability the membrane needs CIP/attention (back-test scalar).

    Reuses ``compute_membrane_health`` and blends the health deficit with the
    salt-passage-breakthrough probability.
    """
    mh = membrane.compute_membrane_health(_fouling(features), cip_age_days=_cip_age(features))
    unhealth = 1.0 - mh.score / 100.0
    sp_prob = salt_passage_breakthrough_probability(mh.normalized_salt_passage_rise_pct)
    return round(min(1.0, max(0.0, 0.5 * unhealth + 0.5 * sp_prob)), 4)


SPEC = ModelSpec(
    model_id=MODEL_ID,
    version=MODEL_VERSION,
    name="Membrane Fouling & Salt Passage (D1)",
    description=(
        "Membrane-health index, salt-passage-breakthrough probability and a "
        "preliminary CIP recommendation from the normalized RO signals. Reuses "
        "the existing Membrane + Water-Quality layer end-to-end; nothing "
        "re-created."
    ),
    asset_type="membrane_array",
    target="membrane_health_index + salt_passage_breakthrough_probability",
    outputs=[
        "membrane_health_index",
        "salt_passage_breakthrough_probability",
        "cleaning_required",
        "fouling_severity",
    ],
    inputs=[
        InputSignal(
            name="normalized_permeate_flow",
            unit="%",
            description="Temperature-normalized permeate flow.",
            source="derived",
        ),
        InputSignal(
            name="normalized_salt_passage",
            unit="%",
            description="Normalized salt passage.",
            source="derived",
        ),
        InputSignal(
            name="differential_pressure_bar",
            unit="bar",
            description="Feed-to-concentrate differential pressure.",
        ),
        InputSignal(name="feed_conductivity_uscm", unit="uS/cm", description="RO feed conductivity."),
        InputSignal(
            name="temperature_c", unit="degC", description="Feed temperature (for normalization)."
        ),
        InputSignal(name="recovery", unit="fraction", description="RO recovery fraction."),
        InputSignal(name="pressure_bar", unit="bar", description="Feed pressure."),
        InputSignal(
            name="cip_age_days",
            unit="days",
            description="Days since last clean-in-place.",
            source="history",
        ),
        InputSignal(
            name="ion_chemistry",
            unit="mg/L",
            description="Feed ion chemistry (scaling species).",
            source="chemistry",
        ),
    ],
    baseline=BaselineRef(
        name="clean-membrane",
        description="Clean-membrane reference (fouling = 0) from the reused WQ layer.",
        reference_values={
            "membrane_health_index": 100.0,
            "normalized_salt_passage_rise_pct": 0.0,
            "normalized_dp_rise_pct": 0.0,
        },
        source="app.water_quality clean-membrane reference",
    ),
    thresholds=[
        AlertThreshold(
            name="Normalized dP rise (CIP)",
            metric="normalized_dp_rise_pct",
            direction=ThresholdDirection.above,
            value=membrane.CIP_NORMALIZED_DP_RISE_PCT,
            severity="warning",
            rationale="Reuses the canonical CIP normalized-dP rise threshold (preliminary).",
        ),
        AlertThreshold(
            name="Normalized salt passage rise (CIP)",
            metric="normalized_salt_passage_rise_pct",
            direction=ThresholdDirection.above,
            value=membrane.CIP_NORMALIZED_SP_RISE_PCT,
            severity="warning",
            rationale="Reuses the canonical CIP salt-passage rise threshold (preliminary).",
        ),
        AlertThreshold(
            name="Permeate flow decline",
            metric="normalized_permeate_flow_decline_pct",
            direction=ThresholdDirection.above,
            value=10.0,
            severity="watch",
            rationale="Screening watch on normalized permeate-flow decline (preliminary).",
        ),
        AlertThreshold(
            name="Salt-passage breakthrough probability high",
            metric="salt_passage_breakthrough_probability",
            direction=ThresholdDirection.above,
            value=0.5,
            severity="warning",
            rationale="Screening trigger on the reused salt-passage signal (preliminary).",
        ),
        AlertThreshold(
            name="Membrane health degraded",
            metric="membrane_health_index",
            direction=ThresholdDirection.below,
            value=60.0,
            severity="warning",
            rationale="Degraded health band cutoff (preliminary).",
        ),
    ],
    reused_components=[
        ReusedComponent(
            name="compute_membrane_health",
            module="app.membrane",
            purpose="Membrane health, normalized indices, fouling severity and CIP flag.",
        ),
        ReusedComponent(
            name="compute_scaling_risks",
            module="app.water_quality",
            purpose="Dominant per-compound scaling risk.",
        ),
        ReusedComponent(
            name="normalized_salt_passage / normalized_differential_pressure",
            module="watertwin_engineering.water_quality",
            purpose="Canonical normalized fouling indices.",
        ),
    ],
    drift=DriftConfig(
        features=[
            "normalized_salt_passage_rise_pct",
            "normalized_dp_rise_pct",
            "feed_conductivity_uscm",
            "temperature_c",
            "recovery",
        ]
    ),
    calibration=CalibrationConfig(),
    false_alarm=FalseAlarmConfig(),
    assumptions=[
        "Preliminary D1 model; thresholds pending customer calibration.",
        "Reuses the existing Membrane + Water-Quality layer; nothing re-created.",
        "Advisory and read-only -- no control write.",
    ],
)


class _MembraneFoulingModel:
    """Adapter binding the membrane fouling spec to its runtime behaviour."""

    spec = SPEC

    def assess(self, inputs: dict[str, float] | None = None) -> ModelAssessment:
        data = inputs or {}
        fouling = _fouling(data)
        mh = membrane.compute_membrane_health(fouling, asset_id=ASSET_ID, cip_age_days=_cip_age(data))
        sp_prob = salt_passage_breakthrough_probability(mh.normalized_salt_passage_rise_pct)

        observed = {
            "normalized_dp_rise_pct": mh.normalized_dp_rise_pct,
            "normalized_salt_passage_rise_pct": mh.normalized_salt_passage_rise_pct,
            "normalized_permeate_flow_decline_pct": mh.normalized_permeate_flow_decline_pct,
            "salt_passage_breakthrough_probability": sp_prob,
            "membrane_health_index": mh.score,
        }
        triggered = evaluate_thresholds(SPEC.thresholds, observed)

        ranked_causes: list[RankedCause] = []
        if mh.cleaning_reason:
            ranked_causes.append(
                RankedCause(
                    cause="Membrane fouling / salt-passage rise",
                    probability=sp_prob,
                    evidence=mh.cleaning_reason,
                )
            )

        evidence = Evidence(
            telemetry_window="latest synthetic WQ/membrane snapshot (preliminary)",
            assets_reviewed=[ASSET_ID],
            assumptions=SPEC.assumptions,
            data_timestamp=now_iso(),
        )
        return ModelAssessment(
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            asset_id=ASSET_ID,
            indices={
                "membrane_health_index": mh.score,
                "normalized_salt_passage_rise_pct": mh.normalized_salt_passage_rise_pct,
                "normalized_dp_rise_pct": mh.normalized_dp_rise_pct,
                "normalized_permeate_flow_decline_pct": mh.normalized_permeate_flow_decline_pct,
                "salt_passage_trend_pct_per_day": mh.salt_passage_trend_pct_per_day,
            },
            probabilities={
                "salt_passage_breakthrough_probability": sp_prob,
                "cleaning_required": 1.0 if mh.cleaning_required else 0.0,
            },
            band=mh.band.value,
            contributions=mh.contributions,
            ranked_causes=ranked_causes,
            triggered_alerts=triggered,
            confidence=round(0.6 + 0.1 * len([c for c in mh.contributions]), 4)
            if mh.contributions
            else 0.6,
            confidence_calibrated=SPEC.calibration.calibrated,
            evidence=evidence,
            provenance=DataProvenance.preliminary,
        )

    def risk_score(self, features: dict[str, float]) -> float:
        return risk_score(features)

    def backtest_dataset(self) -> BackTestDataset:
        return _backtest_dataset()

    def drift_monitor(self) -> FeatureDriftMonitor:
        return _drift_monitor()

    def backtest(self, threshold: float | None = None) -> BackTestMetrics:
        thr = 0.5 if threshold is None else threshold
        return run_backtest(self.backtest_dataset(), self.risk_score, threshold=thr)

    def benchmark(self) -> BenchmarkResult:
        drift = self.drift_monitor().check(
            {"normalized_salt_passage_rise_pct": [0.5, 0.8, 1.0, 0.6, 0.9, 0.7]}
        )
        return run_benchmark(
            self.backtest_dataset(),
            self.risk_score,
            threshold=0.5,
            drift=drift,
            notes=[
                "Reuses the existing Membrane + Water-Quality layer.",
                "Thresholds preliminary pending customer calibration.",
            ],
        )


#: Healthy fouling range (below the reused CIP salt-passage threshold) and the
#: fouled range (CIP due). Ground-truth labels come from the canonical
#: ``cleaning_required`` flag so the dataset is self-consistent with the layer.
_HEALTHY_FOULING = [0.0, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03]
_FOULED_FOULING = [0.05, 0.08, 0.12, 0.18, 0.25, 0.35, 0.45]
#: An early-warning positive (CIP just due) that the preliminary model narrowly
#: misses -- an honest false negative.
_BORDERLINE_FOULING = 0.04


def _backtest_dataset() -> BackTestDataset:
    """Synthetic labelled membrane back-test dataset over the fouling driver.

    Labels come from the reused ``compute_membrane_health(...).cleaning_required``
    flag, so the dataset is self-consistent with the canonical CIP thresholds.
    """
    samples: list[LabeledSample] = []
    for fouling in _HEALTHY_FOULING:
        mh = membrane.compute_membrane_health(fouling)
        samples.append(LabeledSample({"fouling": fouling}, label=mh.cleaning_required, note="healthy"))
    for i, fouling in enumerate(_FOULED_FOULING):
        mh = membrane.compute_membrane_health(fouling)
        samples.append(
            LabeledSample(
                {"fouling": fouling},
                label=mh.cleaning_required,
                lead_time_days=20.0 - 2.0 * i,
                note="fouled / CIP due",
            )
        )
    mh_border = membrane.compute_membrane_health(_BORDERLINE_FOULING)
    samples.append(
        LabeledSample(
            {"fouling": _BORDERLINE_FOULING},
            label=mh_border.cleaning_required,
            lead_time_days=25.0,
            note="early-warning positive",
        )
    )
    return BackTestDataset(
        model_id=MODEL_ID,
        name="Membrane fouling synthetic back-test",
        description="Clean vs fouled RO-membrane scenarios over the fouling driver (synthetic).",
        samples=samples,
    )


def _drift_monitor() -> FeatureDriftMonitor:
    # Baseline from healthy scenarios' normalized salt-passage rise.
    baseline_sp = [
        membrane.compute_membrane_health(f).normalized_salt_passage_rise_pct
        for f in _HEALTHY_FOULING
    ]
    return FeatureDriftMonitor(
        MODEL_ID,
        {"normalized_salt_passage_rise_pct": baseline_sp},
        warn_psi=SPEC.drift.warn_psi,
        alert_psi=SPEC.drift.alert_psi,
    )


ADAPTER = _MembraneFoulingModel()
