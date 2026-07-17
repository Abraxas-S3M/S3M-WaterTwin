"""Downloadable scenario-report generation.

Renders a completed Simulation Center run (baseline vs scenario, impacts, the
recommended response, confidence, and full provenance) into a self-contained
Markdown document. Every report ends with the mandatory *boundary footer* that
restates the advisory, read-only control posture so a report can never be
mistaken for an authorization to act on plant equipment.
"""

from __future__ import annotations

from typing import Any

from canonical_water_model import (
    COMPLIANCE_DISCLAIMER,
    ComplianceEvaluation,
    ComplianceLimit,
    ControlBoundary,
    LimitBound,
    now_iso,
)

REPORT_DISCLAIMER = (
    "This report is advisory and preliminary. All figures are read-only what-if "
    "simulation output (provenance = simulated), not measured or validated plant "
    "data, and must not be used as an autonomous control action."
)


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.2f}{suffix}"
    return f"{value}{suffix}"


def build_scenario_report(job_id: str, run: dict[str, Any]) -> str:
    """Return a Markdown scenario report for a completed run keyed by ``job_id``."""
    scenario_result = run.get("scenario_result", {}) or {}
    comparison = run.get("comparison", {}) or {}
    recommendation = run.get("recommendation") or {}
    confidence = run.get("confidence")
    boundary = ControlBoundary()

    scenario_name = scenario_result.get("scenario", run.get("scenario", "unknown"))
    provenance = scenario_result.get("provenance", "simulated")
    status = scenario_result.get("status", "preliminary")
    engine = scenario_result.get("engine", "EPANET (via WNTR)")
    facility_id = run.get("facility_id", "S3M-DESAL-01")
    train_id = run.get("train_id", "RO-TRAIN-001")

    lines: list[str] = []
    lines.append(f"# Scenario Report - {scenario_name}")
    lines.append("")
    lines.append(f"- Report ID: `report-{job_id}`")
    lines.append(f"- Simulation job ID: `{job_id}`")
    lines.append(f"- Facility / train: `{facility_id}` / `{train_id}`")
    lines.append(f"- Generated at: {now_iso()}")
    lines.append(f"- Engine: {engine}")
    lines.append(f"- Provenance: **{provenance}** &middot; Status: **{status}**")
    lines.append("")

    # Baseline vs scenario ----------------------------------------------------
    lines.append("## Baseline vs scenario")
    lines.append("")
    lines.append("| Metric | Baseline | Scenario | Delta |")
    lines.append("| --- | --- | --- | --- |")
    lines.append(
        "| Delivered flow (m3/h) | "
        f"{_fmt(comparison.get('delivered_flow_baseline_m3h'))} | "
        f"{_fmt(comparison.get('delivered_flow_scenario_m3h'))} | "
        f"{_fmt(comparison.get('delivered_flow_delta_m3h'))} |"
    )
    lines.append(
        "| Min node pressure (m) | "
        f"{_fmt(comparison.get('min_pressure_baseline_m'))} | "
        f"{_fmt(comparison.get('min_pressure_scenario_m'))} | - |"
    )
    lines.append("")

    # Impacts -----------------------------------------------------------------
    lines.append("## Impacts")
    lines.append("")
    delta_pct = comparison.get("delivered_flow_delta_pct")
    lines.append(f"- Delivered-flow change: {_fmt(delta_pct, '%')}")
    violations = scenario_result.get("constraint_violations", []) or []
    if violations:
        lines.append(f"- Constraint violations detected: {len(violations)}")
        for v in violations:
            lines.append(
                f"  - `{v.get('element_id')}` {v.get('metric')} = "
                f"{_fmt(v.get('value'))} (limit {_fmt(v.get('limit'))}, "
                f"{v.get('severity', 'warning')})"
            )
    else:
        lines.append("- Constraint violations detected: none")
    lines.append("")

    # Recommended response ----------------------------------------------------
    lines.append("## Recommended response")
    lines.append("")
    if recommendation:
        lines.append(f"- Recommendation ID: `{recommendation.get('recommendation_id', 'n/a')}`")
        lines.append(f"- Summary: {recommendation.get('summary', 'n/a')}")
        lines.append(f"- Recommended action: {recommendation.get('recommended_action', 'n/a')}")
        lines.append(
            f"- Approval status: **{recommendation.get('approval_status', 'pending')}** "
            "(operator approval required)"
        )
        causes = recommendation.get("ranked_causes", []) or []
        if causes:
            lines.append("- Ranked causes:")
            for c in causes:
                lines.append(
                    f"  - {c.get('cause')} (p={_fmt(c.get('probability'))}): {c.get('evidence')}"
                )
        rec_conf = recommendation.get("confidence", confidence)
    else:
        lines.append("- No recommendation was generated for this run.")
        rec_conf = confidence
    lines.append("")

    # Confidence --------------------------------------------------------------
    lines.append("## Confidence")
    lines.append("")
    lines.append(f"- Model confidence: {_fmt(rec_conf)}")
    lines.append("")

    # Provenance --------------------------------------------------------------
    lines.append("## Provenance")
    lines.append("")
    simulation_ids = run.get("simulation_ids") or []
    lines.append(f"- Simulation IDs: {', '.join(f'`{s}`' for s in simulation_ids) or 'n/a'}")
    lines.append(f"- Data provenance: {provenance}")
    lines.append(f"- Result status: {status}")
    assumptions = scenario_result.get("assumptions", []) or []
    if assumptions:
        lines.append("- Assumptions:")
        for a in assumptions:
            lines.append(f"  - {a}")
    lines.append("")

    # Boundary footer (mandatory) --------------------------------------------
    lines.append("---")
    lines.append("")
    lines.append("## Control boundary (read-only, advisory)")
    lines.append("")
    lines.append(f"- control_mode: `{boundary.control_mode}`")
    lines.append(
        f"- operator_approval_required: `{str(boundary.operator_approval_required).lower()}`"
    )
    lines.append(f"- control_write_enabled: `{str(boundary.control_write_enabled).lower()}`")
    lines.append("")
    lines.append(f"> {REPORT_DISCLAIMER}")
    lines.append("")

    return "\n".join(lines)


def _bound_phrase(bound: LimitBound) -> str:
    return "≤" if bound == LimitBound.max else "≥"


def build_compliance_report(
    evaluation: ComplianceEvaluation,
    limits: list[ComplianceLimit],
    *,
    report_id: str | None = None,
) -> str:
    """Return a printable Markdown regulatory-compliance summary.

    Screens the current (synthetic) water-quality values against the configured
    per-parameter regulatory limits, flagging every exceedance with its
    regulatory basis (provenance). The document ends with the mandatory
    read-only boundary footer + the standard compliance disclaimer so it can
    never be mistaken for a certified regulatory submission or an authorization
    to act on plant equipment.
    """
    boundary = evaluation.control_boundary or ControlBoundary()
    rid = report_id or f"compliance-{evaluation.facility_id}"
    overall = "COMPLIANT" if evaluation.compliant else "EXCEEDANCES DETECTED"

    lines: list[str] = []
    lines.append("# Regulatory Compliance Summary")
    lines.append("")
    lines.append(f"- Report ID: `{rid}`")
    lines.append(f"- Facility / train: `{evaluation.facility_id}` / `{evaluation.train_id}`")
    lines.append(f"- Generated at: {evaluation.generated_at or now_iso()}")
    if evaluation.scenario_fouling is not None:
        lines.append(f"- Scenario fouling severity: {_fmt(evaluation.scenario_fouling)}")
    lines.append(f"- Provenance: **{evaluation.provenance.value}**")
    lines.append(f"- Overall status: **{overall}**")
    lines.append(
        f"- Checks evaluated: {len(evaluation.checks)} · "
        f"Exceedances: **{len(evaluation.exceedances)}**"
    )
    lines.append("")

    # Configured limits (the A1 config store) ---------------------------------
    lines.append("## Configured limits (A1 config store)")
    lines.append("")
    lines.append("| Parameter | Stage | Limit | Unit | Basis |")
    lines.append("| --- | --- | --- | --- | --- |")
    for limit in limits:
        lines.append(
            f"| {limit.display_name} (`{limit.parameter}`) | {limit.stage} | "
            f"{_bound_phrase(limit.bound)} {_fmt(limit.limit)} | {limit.unit} | {limit.basis} |"
        )
    lines.append("")

    # Exceedances (flagged) ---------------------------------------------------
    lines.append("## Exceedances")
    lines.append("")
    if evaluation.exceedances:
        lines.append("| Parameter | Stage | Value | Limit | Over by | Basis |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for ex in evaluation.exceedances:
            lines.append(
                f"| **{ex.display_name}** (`{ex.parameter}`) | {ex.stage} | "
                f"{_fmt(ex.value)} {ex.unit} | {_bound_phrase(ex.bound)} {_fmt(ex.limit)} "
                f"{ex.unit} | {_fmt(ex.exceedance_pct, '%')} | {ex.basis} |"
            )
    else:
        lines.append("- No exceedances against the configured limits.")
    lines.append("")

    # Full screening ----------------------------------------------------------
    lines.append("## All checks")
    lines.append("")
    lines.append("| Parameter | Stage | Value | Limit | Within limit |")
    lines.append("| --- | --- | --- | --- | --- |")
    for check in evaluation.checks:
        flag = "yes" if check.within_limit else "**NO**"
        lines.append(
            f"| {check.display_name} (`{check.parameter}`) | {check.stage} | "
            f"{_fmt(check.value)} {check.unit} | {_bound_phrase(check.bound)} "
            f"{_fmt(check.limit)} {check.unit} | {flag} |"
        )
    lines.append("")

    # Provenance --------------------------------------------------------------
    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- Data provenance: {evaluation.provenance.value}")
    lines.append(
        "- Limits are operator-configured (A1 config store); each row carries its "
        "regulatory basis above."
    )
    lines.append(
        "- Values are synthetic/preliminary engineering estimates, not measured or "
        "validated plant data."
    )
    lines.append("")

    # Boundary footer (mandatory) --------------------------------------------
    lines.append("---")
    lines.append("")
    lines.append("## Control boundary (read-only, advisory)")
    lines.append("")
    lines.append(f"- control_mode: `{boundary.control_mode}`")
    lines.append(
        f"- operator_approval_required: `{str(boundary.operator_approval_required).lower()}`"
    )
    lines.append(f"- control_write_enabled: `{str(boundary.control_write_enabled).lower()}`")
    lines.append("")
    lines.append(f"> {COMPLIANCE_DISCLAIMER}")
    lines.append("")

    return "\n".join(lines)
