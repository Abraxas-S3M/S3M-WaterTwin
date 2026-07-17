"""Recommendation store + builder.

Builds a canonical :class:`RecommendationCard` from a hydraulic what-if result and
attaches the run's ``simulation_id`` to ``evidence.simulation_ids`` so operators
can trace the recommendation back to the exact simulation that supports it.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Optional
from uuid import uuid4

from canonical_water_model import (
    ControlBoundary,
    Evidence,
    RankedCause,
    RecommendationCard,
    now_iso,
)
from simulation_contracts import ScenarioType, SimulationResult


class RecommendationStore:
    """Thread-safe JSON-file-backed store of recommendation cards."""

    def __init__(self, path: str) -> None:
        self._path = os.path.abspath(path)
        self._lock = threading.RLock()
        self._items: dict[str, RecommendationCard] = {}
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
        for rid, data in raw.items():
            try:
                self._items[rid] = RecommendationCard.model_validate(data)
            except Exception:
                continue

    def _flush(self) -> None:
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({k: v.model_dump(mode="json") for k, v in self._items.items()}, fh, indent=2)
        os.replace(tmp, self._path)

    def put(self, card: RecommendationCard) -> RecommendationCard:
        with self._lock:
            self._items[card.recommendation_id] = card
            self._flush()
            return card

    def get(self, recommendation_id: str) -> Optional[RecommendationCard]:
        with self._lock:
            return self._items.get(recommendation_id)

    def list(self) -> list[RecommendationCard]:
        with self._lock:
            return sorted(self._items.values(), key=lambda c: c.created_at, reverse=True)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._flush()


def _summarize(result: SimulationResult) -> tuple[str, str, list[RankedCause]]:
    out = result.outputs
    delta = out.delta_vs_baseline
    causes: list[RankedCause] = []

    if result.scenario == ScenarioType.pump_outage and delta is not None:
        drop = delta.delivered_flow_delta_m3h or 0.0
        pct = delta.delivered_flow_delta_pct or 0.0
        summary = (
            f"Simulated pump outage reduces delivered product water by "
            f"{abs(drop):.0f} m3/h ({abs(pct):.1f}%)."
        )
        action = (
            "Stage the standby product-water pump and pre-position crews before "
            "taking a duty pump offline; verify handoff pressure stays above 25 m."
        )
        causes.append(
            RankedCause(
                cause="Loss of parallel pumping capacity",
                probability=0.9,
                evidence=f"Delivered flow {delta.delivered_flow_scenario_m3h:.0f} vs "
                f"{delta.delivered_flow_baseline_m3h:.0f} m3/h baseline.",
            )
        )
    elif result.scenario == ScenarioType.leak and out.leak_localization is not None:
        loc = out.leak_localization
        summary = (
            f"Simulated leak localizes to node {loc.suspected_node_id} "
            f"(residual {loc.residual_pressure_m:.1f} m)."
        )
        action = (
            f"Dispatch inspection to the {loc.suspected_node_id} handoff segment; "
            "cross-check with SCADA pressure residuals before isolation."
        )
        causes.append(
            RankedCause(
                cause=f"Emitter/leak near {loc.suspected_node_id}",
                probability=0.7,
                evidence=f"Largest pressure residual at {loc.suspected_node_id}.",
            )
        )
    else:
        summary = f"Simulated {result.scenario.value} what-if completed."
        action = "Review the baseline-vs-scenario deltas with the operations team."

    if result.constraint_violations:
        summary += f" {len(result.constraint_violations)} constraint violation(s) detected."

    return summary, action, causes


def build_recommendation(
    result: SimulationResult,
    facility_id: str = "S3M-DESAL-01",
    train_id: str = "RO-TRAIN-001",
    extra_simulation_ids: Optional[list[str]] = None,
) -> RecommendationCard:
    """Create a recommendation card with the simulation id attached to evidence."""
    summary, action, causes = _summarize(result)
    simulation_ids = [result.simulation_id] + list(extra_simulation_ids or [])

    evidence = Evidence(
        telemetry_window="n/a (what-if simulation)",
        assets_reviewed=["RO-TRAIN-001"],
        documents_reviewed=[],
        simulation_ids=simulation_ids,
        assumptions=result.assumptions,
        data_timestamp=now_iso(),
    )

    return RecommendationCard(
        recommendation_id=f"rec-{uuid4().hex[:12]}",
        packet_id=f"pkt-{uuid4().hex[:12]}",
        facility_id=facility_id,
        train_id=train_id,
        summary=summary,
        ranked_causes=causes,
        recommended_action=action,
        confidence=result.confidence,
        evidence=evidence,
        control_boundary=ControlBoundary(),
        source_engine_status="hydraulic-sim: simulated (preliminary)",
        created_at=now_iso(),
    )
