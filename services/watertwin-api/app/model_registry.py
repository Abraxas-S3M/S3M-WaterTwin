"""Model governance registry (D1/D2 governance, advisory + read-only).

Exposes a governance view of the platform's deterministic analytical models --
their version, spec (inputs/outputs/method/assumptions), current headline
metrics, and a drift status derived from a registered reference baseline.

Drift is computed deterministically: each model's reference metrics are taken
from the clean-membrane baseline (``fouling = 0``) and compared against the
metrics recomputed at the requested operating point. The relative change drives
a coarse :class:`DriftStatus` (``stable`` / ``watch`` / ``drifting``).

Everything here is **advisory and preliminary**. The registered models are
deterministic engineering models on synthetic data -- never validated production
models -- and none of them writes to a control system. Governance is a
read-only transparency surface, not a control action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from canonical_water_model import (
    ControlBoundary,
    DataProvenance,
    DriftStatus,
    ModelMetric,
    ModelRegistryEntry,
    ModelSpec,
    now_iso,
)

from . import energy
from . import membrane
from . import predictive_maintenance as pdm
from . import water_quality as wq

#: Baseline operating point (clean membrane) the reference metrics are taken at.
_BASELINE_FOULING = 0.0

#: Default drift thresholds on the absolute relative change from the baseline.
_WATCH_PCT = 10.0
_DRIFT_PCT = 30.0


@dataclass
class _MetricSpec:
    """A single headline metric a model exposes to governance."""

    name: str
    unit: Optional[str]
    #: Extract the raw metric value from a shared, per-fouling context.
    extract: Callable[["_Context"], Optional[float]]


@dataclass
class _ModelDef:
    """Static governance definition of one registered model."""

    model_id: str
    name: str
    version: str
    track: str
    engine: str
    description: str
    spec: ModelSpec
    metrics: list[_MetricSpec] = field(default_factory=list)
    watch_pct: float = _WATCH_PCT
    drift_pct: float = _DRIFT_PCT


@dataclass
class _Context:
    """Cached, per-fouling engine outputs shared across all metric extractors."""

    fouling: float
    _snapshot: object = None
    _membrane: object = None
    _ranking: object = None
    _energy: object = None

    @property
    def snapshot(self):
        if self._snapshot is None:
            self._snapshot = wq.compute_snapshot(self.fouling)
        return self._snapshot

    @property
    def membrane(self):
        if self._membrane is None:
            self._membrane = membrane.compute_membrane_health(self.fouling)
        return self._membrane

    @property
    def ranking(self):
        if self._ranking is None:
            self._ranking = pdm.compute_ranking(self.fouling)
        return self._ranking

    @property
    def energy(self):
        if self._energy is None:
            self._energy = energy.optimization_result(self.fouling)
        return self._energy


def _top_pdm_metric(ctx: _Context, attr: str) -> Optional[float]:
    ranking = ctx.ranking
    if not ranking:
        return None
    return float(getattr(ranking[0], attr))


_MODELS: list[_ModelDef] = [
    _ModelDef(
        model_id="water-quality-ro",
        name="Water Quality — canonical RO model",
        version="1.3.0",
        track="D1",
        engine="watertwin_engineering.ro_performance",
        description=(
            "Single canonical lumped reverse-osmosis model driving recovery, salt "
            "rejection, permeate quality and normalized indices across the plant."
        ),
        spec=ModelSpec(
            inputs=[
                "feed_flow_m3h",
                "feed_tds_mg_l",
                "feed_pressure_bar",
                "membrane_area_m2",
                "salt_transport_coefficient_b_lmh",
                "temperature_c",
            ],
            outputs=[
                "recovery",
                "salt_rejection",
                "permeate_tds_mg_l",
                "normalized_salt_passage",
            ],
            method="Deterministic solution-diffusion RO mass balance (single canonical engine).",
            assumptions=[
                "Lumped single-stage reference train; screening-grade physics.",
                "Synthetic Arabian-Gulf seawater intake composition.",
            ],
        ),
        metrics=[
            _MetricSpec("recovery", None, lambda c: c.snapshot.recovery),
            _MetricSpec("salt_rejection", None, lambda c: c.snapshot.salt_rejection),
            _MetricSpec("permeate_tds_mg_l", "mg/L", lambda c: c.snapshot.permeate_tds_mg_l),
            _MetricSpec(
                "normalized_salt_passage", None, lambda c: c.snapshot.normalized_salt_passage
            ),
        ],
    ),
    _ModelDef(
        model_id="membrane-health",
        name="Membrane Health & Fouling",
        version="1.2.0",
        track="D2",
        engine="app.membrane (reuses the Water Quality layer)",
        description=(
            "Preliminary membrane health from normalized permeate-flow decline, "
            "salt-passage rise and differential-pressure rise plus fouling severity."
        ),
        spec=ModelSpec(
            inputs=[
                "normalized_salt_passage",
                "normalized_differential_pressure",
                "fouling_severity",
                "cip_age_days",
            ],
            outputs=[
                "health_score",
                "normalized_salt_passage_rise_pct",
                "normalized_dp_rise_pct",
                "cleaning_required",
            ],
            method="Visible-penalty health scoring over normalized WQ signals.",
            assumptions=[
                "Reuses the canonical WQ normalized indices (no separate calibration).",
                "Screening-grade fouling severity, not a validated fouling model.",
            ],
        ),
        metrics=[
            _MetricSpec("health_score", None, lambda c: c.membrane.score),
            _MetricSpec(
                "normalized_salt_passage_rise_pct",
                "%",
                lambda c: c.membrane.normalized_salt_passage_rise_pct,
            ),
            _MetricSpec(
                "normalized_dp_rise_pct", "%", lambda c: c.membrane.normalized_dp_rise_pct
            ),
        ],
    ),
    _ModelDef(
        model_id="predictive-maintenance",
        name="Predictive Maintenance (RUL & failure probability)",
        version="1.1.0",
        track="D2",
        engine="watertwin_engineering (component_health / rul / failure_probability)",
        description=(
            "Preliminary remaining-useful-life, failure probability and maintenance "
            "priority ranking across the critical assets of the reference train."
        ),
        spec=ModelSpec(
            inputs=[
                "component_telemetry",
                "health_trend",
                "duty_cycle",
                "maintenance_age_days",
                "anomaly_score",
            ],
            outputs=[
                "rank_score",
                "failure_probability_30d",
                "rul_days",
            ],
            method="Screening RUL + hazard model with a transparent priority rank.",
            assumptions=[
                "Preliminary engineering estimates with uncertainty, not validated.",
                "Ranking reflects the highest-risk asset first.",
            ],
        ),
        metrics=[
            _MetricSpec("top_rank_score", None, lambda c: _top_pdm_metric(c, "rank_score")),
            _MetricSpec(
                "top_failure_probability_30d",
                None,
                lambda c: _top_pdm_metric(c, "failure_probability_30d"),
            ),
        ],
    ),
    _ModelDef(
        model_id="energy-optimization",
        name="Energy Optimization (specific energy)",
        version="1.0.1",
        track="D2",
        engine="watertwin_engineering.energy (bounded RO optimisation)",
        description=(
            "Constrained RO operating-point optimisation minimising specific energy "
            "consumption; reports baseline vs optimised SEC and ESTIMATED savings."
        ),
        spec=ModelSpec(
            inputs=[
                "feed_state",
                "membrane_state",
                "operating_constraints",
            ],
            outputs=[
                "baseline_sec_kwh_m3",
                "optimized_sec_kwh_m3",
                "sec_reduction_pct",
            ],
            method="scipy bounded minimisation over the deterministic RO model.",
            assumptions=[
                "Savings are ESTIMATED on synthetic data, not validated or guaranteed.",
                "Optimiser never violates a constraint.",
            ],
        ),
        metrics=[
            _MetricSpec("baseline_sec_kwh_m3", "kWh/m³", lambda c: c.energy.baseline_sec_kwh_m3),
            _MetricSpec("optimized_sec_kwh_m3", "kWh/m³", lambda c: c.energy.optimized_sec_kwh_m3),
        ],
    ),
    _ModelDef(
        model_id="hydraulic-whatif",
        name="Hydraulic What-If (EPANET/WNTR)",
        version="1.0.0",
        track="D1",
        engine="hydraulic-sim (EPANET via WNTR)",
        description=(
            "Read-only steady-state hydraulic what-if for pump-outage / leak "
            "scenarios; served by the hydraulic-sim service on demand."
        ),
        spec=ModelSpec(
            inputs=["network_model", "scenario_type", "scenario_parameters"],
            outputs=["delivered_flow_m3h", "min_pressure_m", "constraint_violations"],
            method="EPANET steady-state solve (read-only what-if, provenance=simulated).",
            assumptions=[
                "Steady-state demand; single reference network.",
                "Evaluated on demand -- no continuously-monitored drift metric.",
            ],
        ),
        metrics=[],
    ),
]


def list_model_ids() -> list[str]:
    """Return the ids of all registered models."""
    return [m.model_id for m in _MODELS]


def _drift_status(def_: _ModelDef, metrics: list[ModelMetric]) -> tuple[DriftStatus, str]:
    """Derive an entry-level drift status from its metrics' baseline deltas."""
    drifts = [abs(m.drift_pct) for m in metrics if m.drift_pct is not None]
    if not drifts:
        return DriftStatus.unknown, "No continuously-monitored metric with a baseline."
    worst = max(drifts)
    if worst >= def_.drift_pct:
        status = DriftStatus.drifting
    elif worst >= def_.watch_pct:
        status = DriftStatus.watch
    else:
        status = DriftStatus.stable
    return status, (
        f"Max metric drift {worst:.1f}% from baseline "
        f"(watch ≥ {def_.watch_pct:.0f}%, drifting ≥ {def_.drift_pct:.0f}%)."
    )


def _rel_pct(value: Optional[float], reference: Optional[float]) -> Optional[float]:
    if value is None or reference is None or reference == 0:
        return None
    return round((value - reference) / abs(reference) * 100.0, 2)


def _safe_extract(spec: _MetricSpec, ctx: _Context) -> Optional[float]:
    """Extract a metric, degrading to ``None`` if the engine cannot evaluate it.

    Some engines (e.g. the bounded energy optimiser) have no feasible solution at
    extreme operating points; governance must still return a registry entry (with
    the metric omitted / drift unknown) rather than fail the whole request.
    """
    try:
        return spec.extract(ctx)
    except Exception:  # noqa: BLE001 - governance never fails on an engine edge case
        return None


def _entry(def_: _ModelDef, current: _Context, baseline: _Context) -> ModelRegistryEntry:
    metrics: list[ModelMetric] = []
    for spec in def_.metrics:
        value = _safe_extract(spec, current)
        reference = _safe_extract(spec, baseline)
        if value is None:
            continue
        metrics.append(
            ModelMetric(
                name=spec.name,
                value=round(float(value), 5),
                unit=spec.unit,
                reference=None if reference is None else round(float(reference), 5),
                drift_pct=_rel_pct(value, reference),
            )
        )
    status, detail = _drift_status(def_, metrics)
    return ModelRegistryEntry(
        model_id=def_.model_id,
        name=def_.name,
        version=def_.version,
        track=def_.track,
        description=def_.description,
        engine=def_.engine,
        spec=def_.spec,
        current_metrics=metrics,
        drift_status=status,
        drift_detail=detail,
        last_evaluated=now_iso(),
        provenance=DataProvenance.preliminary,
        control_boundary=ControlBoundary(),
    )


def build_registry(fouling: float = 0.0) -> list[ModelRegistryEntry]:
    """Build the full model registry evaluated at ``fouling`` (drift vs baseline).

    Metrics are computed at the requested operating point and compared against
    each model's registered clean-membrane baseline to derive the drift status.
    """
    fouling = max(0.0, min(1.0, fouling))
    current = _Context(fouling=fouling)
    baseline = _Context(fouling=_BASELINE_FOULING)
    return [_entry(def_, current, baseline) for def_ in _MODELS]


def get_model(model_id: str, fouling: float = 0.0) -> Optional[ModelRegistryEntry]:
    """Return a single registry entry by id (evaluated at ``fouling``)."""
    for def_ in _MODELS:
        if def_.model_id == model_id:
            fouling = max(0.0, min(1.0, fouling))
            return _entry(def_, _Context(fouling=fouling), _Context(fouling=_BASELINE_FOULING))
    return None
