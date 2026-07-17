"""Regulatory-compliance screening (advisory, read-only).

Screens the current synthetic water-quality values against the per-parameter
regulatory limits held in the A1 config store (:mod:`app.config_store`) and
produces the compliance artifacts (per-limit checks + flagged exceedances).

Everything here is **advisory and preliminary**: the values screened are
synthetic/preliminary engineering estimates, the limits are operator-configured,
and the result is decision support only -- never a certified regulatory
determination or a control action. Nothing writes to any control system.
"""

from __future__ import annotations

from typing import Optional

from canonical_water_model import (
    ComplianceCheck,
    ComplianceEvaluation,
    ComplianceExceedance,
    ComplianceLimit,
    ControlBoundary,
    DataProvenance,
    LimitBound,
    now_iso,
)

from . import water_quality as wq


def _exceedance_pct(value: float, limit: float, bound: LimitBound) -> float:
    """How far ``value`` breaches ``limit`` as a percentage (0 when compliant)."""
    if limit == 0:
        return 0.0
    if bound == LimitBound.max:
        breach = value - limit
    else:  # a minimum bound is breached when the value falls below it
        breach = limit - value
    if breach <= 0:
        return 0.0
    return round(breach / abs(limit) * 100.0, 2)


def check_limit(limit: ComplianceLimit, value: float) -> ComplianceCheck:
    """Screen a single measured ``value`` against a configured ``limit``.

    Pure function (no I/O): returns a :class:`ComplianceCheck` whose
    ``within_limit`` reflects the limit's bound (``max``: value must be at or
    below the limit; ``min``: value must be at or above it).
    """
    if limit.bound == LimitBound.max:
        within = value <= limit.limit
    else:
        within = value >= limit.limit
    return ComplianceCheck(
        parameter=limit.parameter,
        display_name=limit.display_name,
        unit=limit.unit,
        stage=limit.stage,
        value=round(float(value), 4),
        limit=limit.limit,
        bound=limit.bound,
        within_limit=within,
        exceedance_pct=0.0 if within else _exceedance_pct(value, limit.limit, limit.bound),
        basis=limit.basis,
    )


def evaluate(
    limits: list[ComplianceLimit],
    fouling: float = 0.0,
    *,
    facility_id: str = wq.FACILITY_ID,
    train_id: str = wq.TRAIN_ID,
    scenario_fouling: Optional[float] = None,
) -> ComplianceEvaluation:
    """Screen current values against the configured ``limits``.

    For each limit the current value is looked up at the limit's configured
    ``stage`` from the synthetic water-quality composition. Limits whose
    parameter is not measured at that stage are skipped. Any check that fails is
    also collected into ``exceedances`` and flips ``compliant`` to ``False``.
    """
    checks: list[ComplianceCheck] = []
    exceedances: list[ComplianceExceedance] = []

    for limit in limits:
        if not limit.enabled:
            continue
        values = wq.composition_at(fouling, limit.stage)
        value = values.get(limit.parameter)
        if value is None:
            continue
        check = check_limit(limit, value)
        checks.append(check)
        if not check.within_limit:
            exceedances.append(ComplianceExceedance(**check.model_dump()))

    return ComplianceEvaluation(
        facility_id=facility_id,
        train_id=train_id,
        generated_at=now_iso(),
        scenario_fouling=fouling if scenario_fouling is None else scenario_fouling,
        checks=checks,
        exceedances=exceedances,
        compliant=len(exceedances) == 0,
        provenance=DataProvenance.synthetic,
        control_boundary=ControlBoundary(),
    )
