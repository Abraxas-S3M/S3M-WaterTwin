"""Executive Value / ROI engine (advisory, read-only — AGGREGATION ONLY).

Aggregates ESTIMATED benefits from the *existing* platform layers into an
executive value summary and a pilot ROI. It introduces **no new physics**: it
sums outputs already produced by the Predictive Maintenance engine (avoided-
failure cost → downtime avoided + maintenance savings + water-loss avoided +
capex deferred), the Energy Optimization engine (energy savings) and the Water
Quality engine (chemical/dosing savings, best-effort).

CRITICAL HONESTY: every figure here is an ESTIMATED, preliminary number derived
from SYNTHETIC pilot data -- not a validated saving or a guaranteed outcome. Each
artifact carries ``provenance = estimated`` and the explicit
:data:`VALUE_DISCLAIMER`. Nothing here writes to any control system.
"""

from __future__ import annotations

from canonical_water_model import (
    VALUE_DISCLAIMER,
    DataProvenance,
    ExecutiveValueSummary,
    ROIEstimate,
    ValueComponent,
)

from . import energy
from . import predictive_maintenance as pdm
from . import water_quality as wq
from .water_quality import FACILITY_ID, TRAIN_ID

CURRENCY = "USD"

# --- Documented synthetic-pilot economic assumptions -----------------------
WATER_VALUE_PER_M3 = 0.7
PRODUCTION_M3H = 225.0
#: Split of an avoided failure's cost into production-downtime vs repair value.
DOWNTIME_VALUE_FRACTION = 0.6
MAINTENANCE_VALUE_FRACTION = 0.4
#: Baseline annual antiscalant/acid dosing spend (synthetic).
CHEMICAL_BASELINE_ANNUAL = 180000.0
#: Recoverable water losses (leaks/flushing) and the estimated improvement.
WATER_LOSS_BASELINE_M3_DAY = 35.0
WATER_LOSS_IMPROVEMENT_FRACTION = 0.4
#: Replacement values whose deferral (life extension) is partly credited.
MEMBRANE_REPLACEMENT = 600000.0
PUMP_REPLACEMENT = 350000.0
CAPEX_DEFERRAL_FRACTION = 0.12
#: Pilot investment + period used for the illustrative ROI.
PILOT_INVESTMENT = 250000.0
PILOT_PERIOD_MONTHS = 6.0


def _annual_avoided_cost(rec) -> float:
    """Annualise a per-event avoided-failure cost by its expected frequency."""
    annual_prob = min(1.0, rec.failure_probability_30d * 12.0)
    return rec.avoided_failure_cost * annual_prob


def value_summary(fouling: float) -> ExecutiveValueSummary:
    """Aggregate ESTIMATED annualized benefits across the existing layers."""
    recs = pdm.compute_ranking(fouling)

    # --- Predictive-maintenance derived benefits ---------------------------
    total_annual_avoided = sum(_annual_avoided_cost(r) for r in recs)
    downtime_avoided = total_annual_avoided * DOWNTIME_VALUE_FRACTION
    maintenance_savings = total_annual_avoided * MAINTENANCE_VALUE_FRACTION

    # --- Energy savings (Step 1) -------------------------------------------
    energy_opt = energy.optimization_result(fouling)
    energy_savings = energy_opt.estimated_cost_saving_per_day * 365.0

    # --- Chemical / dosing savings (from WQ signals, best-effort) ----------
    snap = wq.compute_snapshot(fouling)
    dominant_scaling_prob = max((r.probability for r in snap.scaling), default=0.0)
    # More scaling headroom (lower risk) => more room to trim antiscalant dosing.
    dosing_reduction_fraction = max(0.0, 0.10 * (1.0 - dominant_scaling_prob))
    chemical_savings = CHEMICAL_BASELINE_ANNUAL * dosing_reduction_fraction

    # --- Water-loss avoided (reduced leakage/flushing, best-effort) --------
    water_loss_avoided = (
        WATER_LOSS_BASELINE_M3_DAY
        * WATER_LOSS_IMPROVEMENT_FRACTION
        * 365.0
        * WATER_VALUE_PER_M3
    )

    # --- Capex deferred (life extension defers replacement) ----------------
    capex_deferred = (MEMBRANE_REPLACEMENT + PUMP_REPLACEMENT) * CAPEX_DEFERRAL_FRACTION

    components = [
        ValueComponent(
            category="downtime_avoided",
            annualized_benefit=round(downtime_avoided, 2),
            basis="PdM avoided-failure cost (production-downtime share), annualized",
            currency=CURRENCY,
            provenance=DataProvenance.estimated,
        ),
        ValueComponent(
            category="energy_savings",
            annualized_benefit=round(energy_savings, 2),
            basis="constrained RO SEC optimization (Step 1) daily saving × 365",
            currency=CURRENCY,
            provenance=DataProvenance.estimated,
        ),
        ValueComponent(
            category="chemical_savings",
            annualized_benefit=round(chemical_savings, 2),
            basis="antiscalant/acid dosing headroom from WQ scaling signals (best-effort)",
            currency=CURRENCY,
            provenance=DataProvenance.estimated,
        ),
        ValueComponent(
            category="water_loss_avoided",
            annualized_benefit=round(water_loss_avoided, 2),
            basis="reduced leakage/flushing losses × water value (best-effort)",
            currency=CURRENCY,
            provenance=DataProvenance.estimated,
        ),
        ValueComponent(
            category="maintenance_savings",
            annualized_benefit=round(maintenance_savings, 2),
            basis="PdM avoided-failure cost (reactive-vs-planned repair share), annualized",
            currency=CURRENCY,
            provenance=DataProvenance.estimated,
        ),
        ValueComponent(
            category="capex_deferred",
            annualized_benefit=round(capex_deferred, 2),
            basis="membrane/pump replacement value deferred by life extension",
            currency=CURRENCY,
            provenance=DataProvenance.estimated,
        ),
    ]
    total = round(sum(c.annualized_benefit for c in components), 2)

    return ExecutiveValueSummary(
        facility_id=FACILITY_ID,
        train_id=TRAIN_ID,
        currency=CURRENCY,
        downtime_avoided=round(downtime_avoided, 2),
        energy_savings=round(energy_savings, 2),
        chemical_savings=round(chemical_savings, 2),
        water_loss_avoided=round(water_loss_avoided, 2),
        maintenance_savings=round(maintenance_savings, 2),
        capex_deferred=round(capex_deferred, 2),
        total_annualized_benefit=total,
        components=components,
        synthetic_basis=True,
        disclaimer=VALUE_DISCLAIMER,
        provenance=DataProvenance.estimated,
    )


def roi(fouling: float) -> ROIEstimate:
    """Illustrative pilot ROI, annualized benefit and payback (ESTIMATED)."""
    summary = value_summary(fouling)
    annual = summary.total_annualized_benefit
    pilot_benefit = annual * (PILOT_PERIOD_MONTHS / 12.0)
    pilot_roi_pct = (
        (pilot_benefit - PILOT_INVESTMENT) / PILOT_INVESTMENT * 100.0
        if PILOT_INVESTMENT > 0
        else 0.0
    )
    payback_months = (
        PILOT_INVESTMENT / (annual / 12.0) if annual > 0 else float("inf")
    )
    return ROIEstimate(
        facility_id=FACILITY_ID,
        train_id=TRAIN_ID,
        currency=CURRENCY,
        pilot_investment=PILOT_INVESTMENT,
        pilot_benefit=round(pilot_benefit, 2),
        pilot_roi_pct=round(pilot_roi_pct, 2),
        annualized_benefit=round(annual, 2),
        payback_period_months=round(payback_months, 2),
        synthetic_basis=True,
        disclaimer=VALUE_DISCLAIMER,
        provenance=DataProvenance.estimated,
    )
