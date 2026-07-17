"""Work-order engine: derive proposed work orders from predictive-maintenance alerts.

For each predictive-maintenance recommendation (a PdM "alert") this module builds
a :class:`~canonical_water_model.MaintenanceWorkOrder` that is fully traceable
back to the originating model and its evidence:

* ``originating_model`` + ``source_recommendation_id`` + ``source_alert_code``
  name the exact model artifact the work order came from,
* ``ranked_causes`` + ``evidence`` carry the supporting evidence, and
* the failure-mode / RUL / cost fields are the preliminary estimates it was
  built from.

Every work order is created ``pending`` operator approval with the read-only
control boundary intact. Nothing here writes to a control system; a work order
is a CMMS ticket proposal, not a device command. It also provides a small
JSON-file-backed :class:`WorkOrderStore` mirroring the recommendation store.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Optional

from canonical_water_model import (
    ControlBoundary,
    DataProvenance,
    Evidence,
    MaintenanceWorkOrder,
    PdMRecommendation,
    RankedCause,
    WorkOrderPriority,
    WorkOrderSource,
    WorkOrderStatus,
    now_iso,
)

from . import predictive_maintenance as pdm
from .water_quality import FACILITY_ID, TRAIN_ID

ORIGINATING_MODEL = "predictive-maintenance"


class WorkOrderStore:
    """Thread-safe JSON-file-backed store of maintenance work orders."""

    def __init__(self, path: str) -> None:
        self._path = os.path.abspath(path)
        self._lock = threading.RLock()
        self._items: dict[str, MaintenanceWorkOrder] = {}
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return
        for wid, data in raw.items():
            try:
                self._items[wid] = MaintenanceWorkOrder.model_validate(data)
            except Exception:
                continue

    def _flush(self) -> None:
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(
                {k: v.model_dump(mode="json") for k, v in self._items.items()},
                fh,
                indent=2,
            )
        os.replace(tmp, self._path)

    def put(self, work_order: MaintenanceWorkOrder) -> MaintenanceWorkOrder:
        with self._lock:
            self._items[work_order.work_order_id] = work_order
            self._flush()
            return work_order

    def get(self, work_order_id: str) -> Optional[MaintenanceWorkOrder]:
        with self._lock:
            return self._items.get(work_order_id)

    def list(self) -> list[MaintenanceWorkOrder]:
        with self._lock:
            return sorted(self._items.values(), key=lambda w: w.created_at, reverse=True)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._flush()


def _priority_from_pdm(rec: PdMRecommendation) -> WorkOrderPriority:
    """Map a PdM recommendation's 30-day failure probability onto a priority."""
    p = rec.failure_probability_30d
    if p >= 0.6:
        return WorkOrderPriority.urgent
    if p >= 0.35:
        return WorkOrderPriority.high
    if p >= 0.15:
        return WorkOrderPriority.medium
    return WorkOrderPriority.low


def _work_order_id(asset_id: str) -> str:
    """Deterministic id so repeated derivation is idempotent."""
    return f"wo-{asset_id.lower()}"


def build_work_order_from_pdm(rec: PdMRecommendation) -> MaintenanceWorkOrder:
    """Build a proposed work order traceable to a predictive-maintenance alert.

    The work order records the originating model + the source recommendation id,
    attaches the model's ranked root causes and an :class:`Evidence` block, and
    is created ``pending`` operator approval with the read-only control boundary
    intact.
    """
    ranking = pdm.root_cause_for(rec.asset_id)
    ranked_causes: list[RankedCause] = list(ranking.ranked_causes)

    evidence = Evidence(
        telemetry_window="live synthetic equipment telemetry (preliminary)",
        assets_reviewed=[rec.asset_id],
        documents_reviewed=[],
        simulation_ids=[],
        assumptions=[
            "Work order derived from a preliminary predictive-maintenance alert "
            "(advisory, not validated).",
            "RUL, failure probability and cost figures are screening estimates "
            "with uncertainty, not guaranteed values.",
            "A work order is a CMMS ticket proposal, not a control/OT command.",
        ],
        data_timestamp=now_iso(),
    )

    title = f"{rec.asset_name or rec.asset_id}: {rec.predicted_failure_mode}"
    description = (
        f"Proposed maintenance for {rec.asset_name or rec.asset_id} derived from "
        f"a predictive-maintenance alert. Predicted failure mode: "
        f"'{rec.predicted_failure_mode}'. Preliminary 30-day failure probability "
        f"{rec.failure_probability_30d:.0%}; RUL {rec.rul_days:.0f} d "
        f"({rec.rul_lower_days:.0f}-{rec.rul_upper_days:.0f} d). "
        f"Plan within ~{rec.time_to_intervention_days:.0f} d. {rec.recommended_window}. "
        f"Advisory only — operator approval required, no control write."
    )

    return MaintenanceWorkOrder(
        work_order_id=_work_order_id(rec.asset_id),
        asset_id=rec.asset_id,
        asset_name=rec.asset_name,
        title=title,
        description=description,
        priority=_priority_from_pdm(rec),
        status=WorkOrderStatus.proposed,
        source=WorkOrderSource.predictive_maintenance,
        originating_model=ORIGINATING_MODEL,
        source_recommendation_id=rec.recommendation_id,
        source_alert_code=f"PDM-{rec.asset_id}",
        predicted_failure_mode=rec.predicted_failure_mode,
        failure_probability_30d=rec.failure_probability_30d,
        rul_days=rec.rul_days,
        recommended_window=rec.recommended_window,
        spares_required=list(rec.spares_required),
        estimated_downtime_hours=rec.expected_downtime_hours,
        estimated_cost=rec.maintenance_cost,
        ranked_causes=ranked_causes,
        evidence=evidence,
        control_boundary=ControlBoundary(),
        provenance=DataProvenance.preliminary,
        created_at=now_iso(),
    )


def propose_work_orders(fouling: float = pdm.DEFAULT_FOULING) -> list[MaintenanceWorkOrder]:
    """Derive proposed work orders from the current PdM recommendations (alerts).

    Ordered highest-risk first (the PdM ranking order).
    """
    recs = pdm.compute_recommendations(fouling)
    return [build_work_order_from_pdm(rec) for rec in recs]


__all__ = [
    "WorkOrderStore",
    "build_work_order_from_pdm",
    "propose_work_orders",
    "ORIGINATING_MODEL",
    "FACILITY_ID",
    "TRAIN_ID",
]
