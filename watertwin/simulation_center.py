"""Simulation Center RO what-if scenario (watertwin-api side).

Compares a baseline RO operating point against a scenario and produces the
deltas the Simulation Center surfaces to operators: energy, water-quality, and
recovery changes plus a confidence score. The confidence is grounded in an
independent cross-check of the scenario against ``watertwin.calculations`` (the
API's analytical RO reference) -- large disagreement lowers confidence because
it is a bug/uncertainty signal.

The ``simulation_id`` of each underlying treatment-sim job is threaded into the
canonical :class:`Evidence` block so downstream packets can trace the result
back to its simulation, and everything is tagged read-only/advisory.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from watertwin import calculations

try:  # canonical_water_model is the shared model package (Phase 1).
    from canonical_water_model import ControlBoundary, DataProvenance, Evidence, now_iso
except Exception:  # pragma: no cover - fallback if package not on path
    ControlBoundary = None  # type: ignore
    DataProvenance = None  # type: ignore
    Evidence = None  # type: ignore

    def now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()


class ROScenarioDeltas(BaseModel):
    specific_energy_kwh_m3_baseline: float
    specific_energy_kwh_m3_scenario: float
    specific_energy_delta_kwh_m3: float
    specific_energy_pct_change: float

    recovery_baseline: float
    recovery_scenario: float
    recovery_delta: float

    permeate_tds_baseline_mg_l: float
    permeate_tds_scenario_mg_l: float
    permeate_tds_delta_mg_l: float

    salt_rejection_baseline: float
    salt_rejection_scenario: float
    salt_rejection_delta: float


class ROScenarioResult(BaseModel):
    scenario_id: Optional[str] = None
    engine: str
    deltas: ROScenarioDeltas
    confidence: float = Field(ge=0, le=1)
    cross_check_rel_error: float
    simulation_ids: list[str] = Field(default_factory=list)
    evidence: Optional[dict] = None
    provenance: str = "simulated"
    status: str = "preliminary"
    summary: str = ""


def _pct_change(new: float, old: float) -> float:
    if old == 0:
        return 0.0
    return (new - old) / old * 100.0


def _cross_check_error(scenario_job: dict[str, Any]) -> float:
    """Relative error between the scenario result and the analytical reference."""
    req = scenario_job.get("request", {})
    res = scenario_job.get("result", {})
    feed = req.get("feed", {})
    membrane = req.get("membrane", {})
    operating = req.get("operating", {}) or {}
    try:
        ref = calculations.ro_performance(
            feed_flow_m3h=feed["flow_m3h"],
            feed_tds_mg_l=feed["tds_mg_l"],
            feed_pressure_bar=feed["pressure_bar"],
            membrane_area_m2=membrane["area_m2"],
            a_lmh_bar=membrane.get("a_lmh_bar", 3.0),
            b_lmh=membrane.get("b_lmh", 0.15),
            temperature_c=feed.get("temperature_c", 25.0),
            pump_efficiency=operating.get("pump_efficiency", 0.8),
            erd_efficiency=operating.get("erd_efficiency", 0.95),
            use_erd=operating.get("use_erd", True),
            pressure_drop_bar=operating.get("pressure_drop_bar", 1.0),
        )
    except Exception:
        return 1.0

    def rel(a: float, b: float) -> float:
        return abs(a - b) / b if b else 0.0

    sec_err = rel(res.get("specific_energy_kwh_m3", 0.0), ref.specific_energy_kwh_m3)
    rec_err = rel(res.get("recovery", 0.0), ref.recovery)
    return max(sec_err, rec_err)


def build_ro_scenario(
    baseline_job: dict[str, Any],
    scenario_job: dict[str, Any],
    scenario_id: Optional[str] = None,
    tolerance: float = 0.15,
) -> ROScenarioResult:
    """Build the Simulation Center RO what-if comparison from two sim jobs.

    ``baseline_job`` / ``scenario_job`` are completed treatment-sim job dicts
    (as returned by the treatment-sim client), each with ``job_id``, ``request``
    and ``result`` for a baseline RO simulate call.
    """
    b = baseline_job["result"]
    s = scenario_job["result"]

    deltas = ROScenarioDeltas(
        specific_energy_kwh_m3_baseline=b["specific_energy_kwh_m3"],
        specific_energy_kwh_m3_scenario=s["specific_energy_kwh_m3"],
        specific_energy_delta_kwh_m3=s["specific_energy_kwh_m3"]
        - b["specific_energy_kwh_m3"],
        specific_energy_pct_change=_pct_change(
            s["specific_energy_kwh_m3"], b["specific_energy_kwh_m3"]
        ),
        recovery_baseline=b["recovery"],
        recovery_scenario=s["recovery"],
        recovery_delta=s["recovery"] - b["recovery"],
        permeate_tds_baseline_mg_l=b["permeate_tds_mg_l"],
        permeate_tds_scenario_mg_l=s["permeate_tds_mg_l"],
        permeate_tds_delta_mg_l=s["permeate_tds_mg_l"] - b["permeate_tds_mg_l"],
        salt_rejection_baseline=b["salt_rejection"],
        salt_rejection_scenario=s["salt_rejection"],
        salt_rejection_delta=s["salt_rejection"] - b["salt_rejection"],
    )

    cross_err = _cross_check_error(scenario_job)
    # Confidence: full agreement -> high; error at/above tolerance -> low. The
    # WaterTAP engine (validated flowsheet) earns a small confidence premium.
    engine = s.get("engine", "analytical")
    base_conf = max(0.3, min(0.95, 0.95 - (cross_err / tolerance) * 0.4))
    if engine == "watertap":
        base_conf = min(0.95, base_conf + 0.05)
    confidence = round(base_conf, 2)

    simulation_ids = [baseline_job["job_id"], scenario_job["job_id"]]

    evidence_dict: Optional[dict] = None
    assumptions = [
        "Read-only what-if; results are simulated, not measured or validated.",
        f"Cross-checked vs watertwin.calculations (rel error {cross_err:.3f}).",
        f"Engine: {engine}.",
    ]
    if Evidence is not None:
        evidence = Evidence(
            telemetry_window="what-if (no live telemetry window)",
            assets_reviewed=[],
            documents_reviewed=[],
            simulation_ids=simulation_ids,
            assumptions=assumptions,
            data_timestamp=now_iso(),
        )
        evidence_dict = evidence.model_dump(mode="json")

    sec_delta = deltas.specific_energy_delta_kwh_m3
    tds_delta = deltas.permeate_tds_delta_mg_l
    summary = (
        f"Scenario changes specific energy by {sec_delta:+.2f} kWh/m3 "
        f"({deltas.specific_energy_pct_change:+.1f}%) and permeate TDS by "
        f"{tds_delta:+.0f} mg/L vs baseline (simulated, preliminary)."
    )

    return ROScenarioResult(
        scenario_id=scenario_id,
        engine=engine,
        deltas=deltas,
        confidence=confidence,
        cross_check_rel_error=cross_err,
        simulation_ids=simulation_ids,
        evidence=evidence_dict,
        summary=summary,
    )
