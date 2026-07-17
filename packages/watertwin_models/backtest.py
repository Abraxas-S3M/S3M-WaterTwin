"""D1 back-test harness: score a model against a labelled synthetic dataset.

The harness is deliberately model-agnostic. A caller supplies a
:class:`BackTestDataset` of labelled samples and a ``predict_fn`` that maps a
sample's features to a probability in ``[0, 1]``; :func:`run_backtest` applies a
decision threshold and returns transparent classification metrics
(:class:`BackTestMetrics`) including the **false-alarm rate** and mean detection
**lead time**.

Everything here is pure and deterministic. Datasets are synthetic and stamped
``provenance = preliminary``; metrics are preliminary screening figures pending
customer calibration -- never validated performance guarantees.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, Field

from canonical_water_model import DataProvenance

#: A model prediction function: features mapping -> probability in ``[0, 1]``.
PredictFn = Callable[[dict[str, float]], float]


@dataclass(frozen=True)
class LabeledSample:
    """One labelled back-test sample.

    ``features`` is the model input mapping, ``label`` is the ground-truth event
    (``True`` = the condition the model should raise on was truly present), and
    ``lead_time_days`` (optional) is how far ahead of the true event this sample
    sits -- averaged over correctly-detected positives to report detection lead
    time.
    """

    features: dict[str, float]
    label: bool
    lead_time_days: float | None = None
    note: str = ""


class BackTestDataset(BaseModel):
    """A synthetic, labelled back-test dataset for one model."""

    model_config = {"arbitrary_types_allowed": True, "protected_namespaces": ()}

    model_id: str
    name: str
    description: str
    samples: list[LabeledSample] = Field(default_factory=list)
    synthetic: bool = True
    provenance: DataProvenance = DataProvenance.preliminary

    def positives(self) -> int:
        return sum(1 for s in self.samples if s.label)

    def negatives(self) -> int:
        return sum(1 for s in self.samples if not s.label)


class BackTestMetrics(BaseModel):
    """Transparent back-test classification metrics (preliminary).

    ``false_alarm_rate`` is ``FP / (FP + TN)`` (the fraction of healthy samples
    that raised an alert). ``mean_lead_time_days`` averages the labelled lead
    time over correctly-detected positives (``None`` when unavailable). Metrics
    are preliminary screening figures pending customer calibration.
    """

    model_config = {"protected_namespaces": ()}

    model_id: str
    threshold: float
    samples: int
    positives: int
    negatives: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    accuracy: float
    false_alarm_rate: float
    mean_lead_time_days: float | None = None
    provenance: DataProvenance = DataProvenance.preliminary
    pending_customer_calibration: bool = True


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def run_backtest(
    dataset: BackTestDataset,
    predict_fn: PredictFn,
    threshold: float = 0.5,
) -> BackTestMetrics:
    """Score ``predict_fn`` against ``dataset`` at a decision ``threshold``.

    An alert is raised for a sample when ``predict_fn(features) >= threshold``.
    Returns the full confusion matrix plus precision / recall / F1 / accuracy,
    the false-alarm rate and the mean detection lead time over correctly-detected
    positives.

    Args:
        dataset: The labelled synthetic dataset.
        predict_fn: Maps a sample's features to a probability in ``[0, 1]``.
        threshold: Decision threshold in ``[0, 1]`` (default 0.5).

    Returns:
        A preliminary :class:`BackTestMetrics`.

    Raises:
        ValueError: If ``dataset`` has no samples or ``threshold`` is not in
            ``[0, 1]``.
    """
    if not dataset.samples:
        raise ValueError("dataset must contain at least one labelled sample.")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1].")

    tp = fp = tn = fn = 0
    detected_lead_times: list[float] = []

    for sample in dataset.samples:
        score = float(predict_fn(sample.features))
        alert = score >= threshold
        if sample.label and alert:
            tp += 1
            if sample.lead_time_days is not None:
                detected_lead_times.append(float(sample.lead_time_days))
        elif sample.label and not alert:
            fn += 1
        elif not sample.label and alert:
            fp += 1
        else:
            tn += 1

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    accuracy = _safe_div(tp + tn, tp + fp + tn + fn)
    false_alarm_rate = _safe_div(fp, fp + tn)
    mean_lead = (
        round(sum(detected_lead_times) / len(detected_lead_times), 2)
        if detected_lead_times
        else None
    )

    return BackTestMetrics(
        model_id=dataset.model_id,
        threshold=threshold,
        samples=len(dataset.samples),
        positives=dataset.positives(),
        negatives=dataset.negatives(),
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        accuracy=round(accuracy, 4),
        false_alarm_rate=round(false_alarm_rate, 4),
        mean_lead_time_days=mean_lead,
    )
