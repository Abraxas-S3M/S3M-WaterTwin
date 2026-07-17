"""Back-test harness for condition models.

Runs a :class:`~watertwin_engineering.condition.model_spec.ConditionModel` over a
labelled (or synthetic) history and scores how well its alarms match reality:

* **precision** -- of the samples where the model alarmed, the fraction that were
  genuinely in a degraded/event state (``TP / (TP + FP)``);
* **recall** -- of the samples that were genuinely in an event state, the
  fraction the model caught (``TP / (TP + FN)``);
* **false-alarm rate** -- of the genuinely nominal samples, the fraction the
  model wrongly alarmed on (``FP / (FP + TN)``); and
* **lead time** -- how far *ahead* of each event onset the model first alarmed
  (the operational value of a predictive alert).

Precision and recall are reported with Wilson score confidence intervals so the
metrics carry their own uncertainty (a metric measured on ten samples is not the
same as one measured on ten thousand). Everything is pure and deterministic and
stamped ``provenance = "preliminary"``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .model_spec import PRELIMINARY, ConditionModel

#: Reserved record keys that are never treated as model features.
_RESERVED = ("features", "label", "t", "time", "timestamp")

#: z-multiplier for a two-sided 95% Wilson interval.
_Z_95 = 1.959963984540054

__all__ = [
    "BackTestMetrics",
    "BackTestResult",
    "run_backtest",
    "wilson_interval",
]


def wilson_interval(successes: int, total: int, z: float = _Z_95) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial proportion.

    Unlike the naive ``p +/- z*sqrt(p(1-p)/n)`` interval this stays inside
    ``[0, 1]`` and behaves sensibly for small ``total`` or proportions near the
    boundary. Returns ``(0.0, 0.0)`` for an empty sample.
    """
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    centre = (p + z2 / (2 * total)) / denom
    margin = (z * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total))) / denom
    return (round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4))


@dataclass(frozen=True)
class BackTestMetrics:
    """Confusion-matrix + event metrics for one back-test run."""

    samples: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    false_alarm_rate: float
    f1: float
    precision_ci: tuple[float, float]
    recall_ci: tuple[float, float]
    events_total: int
    events_detected: int
    mean_lead_time: float
    lead_time_unit: str
    provenance: str = PRELIMINARY


@dataclass(frozen=True)
class BackTestResult:
    """The full back-test outcome for a model over a history."""

    model_id: str
    version: str
    method: str
    metrics: BackTestMetrics
    notes: list[str] = field(default_factory=list)
    provenance: str = PRELIMINARY


def _features_of(record: Mapping[str, Any], label_key: str, time_key: str) -> Mapping[str, float]:
    inner = record.get("features")
    if isinstance(inner, Mapping):
        return inner
    return {k: v for k, v in record.items() if k not in (label_key, time_key, *_RESERVED)}


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def run_backtest(
    model: ConditionModel,
    history: Sequence[Mapping[str, Any]],
    *,
    label_key: str = "label",
    time_key: str = "t",
    lead_window: float = math.inf,
) -> BackTestResult:
    """Back-test ``model`` over ``history`` and return metrics with uncertainty.

    Each ``history`` record supplies a feature vector (under a ``"features"``
    key, or the record itself minus the reserved keys), a ground-truth
    ``label`` (truthy = the asset was genuinely in an event/degraded state at
    that sample) and an optional monotonic ``t`` timestamp (defaults to the
    sample index). The model's :meth:`score` decides an ``alarm`` per sample.

    Per-sample the harness accumulates a confusion matrix (precision, recall,
    false-alarm rate, F1, each with a Wilson interval). It then detects *event
    onsets* (label transitions from false to true) and, for each onset,
    measures the **lead time** to the earliest alarm in the preceding
    ``lead_window`` (in ``t`` units); an onset with a pre-onset alarm counts as
    detected and contributes its lead time to the mean.

    Args:
        model: A model implementing the :class:`ConditionModel` protocol; its
            spec is validated before the run.
        history: The labelled/synthetic sequence of samples (chronological).
        label_key: Record key holding the ground-truth event label.
        time_key: Record key holding the timestamp (falls back to the index).
        lead_window: Only alarms within this many ``t`` units before an onset
            count towards lead time (default: unbounded).

    Returns:
        A :class:`BackTestResult` (``provenance = "preliminary"``).

    Raises:
        ValueError: If the model spec is invalid or ``history`` is empty.
    """
    model.spec.validate()
    if not history:
        raise ValueError("history must be a non-empty sequence of labelled samples.")

    tp = fp = tn = fn = 0
    labels: list[bool] = []
    alarms: list[bool] = []
    times: list[float] = []

    for idx, record in enumerate(history):
        features = _features_of(record, label_key, time_key)
        label = bool(record.get(label_key, False))
        alarm = model.score(features).alarm
        t = float(record.get(time_key, idx))

        labels.append(label)
        alarms.append(alarm)
        times.append(t)

        if alarm and label:
            tp += 1
        elif alarm and not label:
            fp += 1
        elif not alarm and not label:
            tn += 1
        else:
            fn += 1

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    false_alarm_rate = _safe_div(fp, fp + tn)
    f1 = _safe_div(2 * precision * recall, precision + recall)

    # --- Event onsets + lead time ------------------------------------------
    events_total = 0
    leads: list[float] = []
    for i in range(len(labels)):
        onset = labels[i] and (i == 0 or not labels[i - 1])
        if not onset:
            continue
        events_total += 1
        onset_t = times[i]
        earliest_lead: float | None = None
        j = i - 1
        while j >= 0 and (onset_t - times[j]) <= lead_window:
            if alarms[j]:
                earliest_lead = onset_t - times[j]
            j -= 1
        if earliest_lead is not None:
            leads.append(earliest_lead)

    mean_lead_time = round(sum(leads) / len(leads), 4) if leads else 0.0

    notes = [
        f"{len(history)} samples; {tp} TP / {fp} FP / {tn} TN / {fn} FN.",
        f"{len(leads)}/{events_total} event onset(s) detected with a pre-onset alarm.",
        "Precision/recall reported with 95% Wilson intervals.",
    ]

    metrics = BackTestMetrics(
        samples=len(history),
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision=round(precision, 4),
        recall=round(recall, 4),
        false_alarm_rate=round(false_alarm_rate, 4),
        f1=round(f1, 4),
        precision_ci=wilson_interval(tp, tp + fp),
        recall_ci=wilson_interval(tp, tp + fn),
        events_total=events_total,
        events_detected=len(leads),
        mean_lead_time=mean_lead_time,
        lead_time_unit=f"{time_key}-units",
    )
    return BackTestResult(
        model_id=model.spec.model_id,
        version=model.spec.version,
        method="per-sample confusion matrix + event-onset lead time",
        metrics=metrics,
        notes=notes,
    )
