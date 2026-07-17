"""Membrane Intelligence: fouling / scaling / health that REUSES the WQ layer.

This module does **not** re-implement any water-quality physics. It imports the
Water Quality Intelligence layer (:mod:`app.water_quality`) and consumes its
already-computed normalized indices -- normalized salt passage, normalized
differential pressure, scaling risks and the RO-feed composition (SDI / UV254 /
ATP) -- to derive membrane-level health, fouling/scaling severity, a
cleaning-in-place (CIP) requirement flag and a preliminary membrane
remaining-useful-life.

Everything here is **advisory and preliminary**. Membrane health uses the same
visible-penalty pattern as the rest of the platform; membrane RUL is a
screening-grade engineering estimate (never a validated or guaranteed
time-to-failure) and is stamped ``provenance = preliminary`` with an uncertainty
band. Nothing in this module writes to any control system.
"""

from __future__ import annotations

from canonical_water_model import (
    DataProvenance,
    FoulingSeverity,
    HealthBand,
    HealthContribution,
    MembraneHealth,
    RemainingUsefulLife,
)
from watertwin_engineering import colloidal_fouling_index, remaining_useful_life_days

from . import water_quality as wq

#: Default membrane-array asset id for the reference RO train.
MEMBRANE_ASSET_ID = "AST-MEMB-01"

#: CIP thresholds on the normalized rises (percent vs the clean baseline). Field
#: practice cleans an RO train at roughly +15% normalized dP or +10% normalized
#: salt passage (documented screening thresholds, advisory only).
CIP_NORMALIZED_DP_RISE_PCT = 15.0
CIP_NORMALIZED_SP_RISE_PCT = 10.0

#: Recommended CIP interval (days) used when projecting membrane RUL.
CIP_INTERVAL_DAYS = 180.0

#: UV254 (per cm) and ATP (pg/mL) reference scales for the organic/biofouling
#: severities (documented screening scales, matching the WQ fouling composite).
_UV254_SCALE = 0.1
_ATP_SCALE = 500.0


def _pct_rise(current: float, baseline: float) -> float:
    """Percent rise of ``current`` over ``baseline`` (0 when baseline <= 0)."""
    if baseline <= 0:
        return 0.0
    return max(0.0, (current - baseline) / baseline * 100.0)


def _fouling_severity(fouling: float, norm_dp_component: float) -> FoulingSeverity:
    """Organic/colloidal/biological/scaling severity from reused WQ signals."""
    comp = wq._composition(fouling)
    feed = comp["ro_feed"]
    sdi = feed.get("sdi", 0.0)
    uv254 = feed.get("uv254_per_cm", 0.0)
    atp = feed.get("atp_pg_ml", 0.0)
    turbidity = feed.get("turbidity_ntu", 0.0)
    particles = feed.get("particle_count_per_ml", 0.0)

    colloidal = colloidal_fouling_index(sdi=sdi, turbidity_ntu=turbidity, particle_count=particles)
    organic = min(1.0, 0.6 * min(1.0, uv254 / _UV254_SCALE) + 0.4 * norm_dp_component)
    biological = min(1.0, 0.7 * min(1.0, atp / _ATP_SCALE) + 0.3 * norm_dp_component)

    # Scaling severity is the worst per-compound scaling probability from the WQ
    # scaling layer (reused, not recomputed here).
    scaling_risks = wq.compute_scaling_risks(fouling)
    scaling = max((r.probability for r in scaling_risks), default=0.0)

    return FoulingSeverity(
        organic=round(organic, 4),
        colloidal=round(colloidal, 4),
        biological=round(biological, 4),
        scaling=round(scaling, 4),
    )


def _underperforming_vessel(severity: FoulingSeverity, scaling_stage: str | None) -> str | None:
    """Pick the vessel/element most likely underperforming (deterministic)."""
    worst = max(
        (severity.scaling, "scaling"),
        (severity.organic, "organic"),
        (severity.colloidal, "colloidal"),
        (severity.biological, "biological"),
        key=lambda item: item[0],
    )
    if worst[0] < 0.35:
        return None
    if worst[1] == "scaling":
        # Scaling concentrates in the tail (last elements of the last stage).
        stage = scaling_stage or "ro_stage_2"
        tag = "stage-2 tail" if "2" in stage else "stage-1 tail"
        return f"RO-1-V18 (element 6, {tag})"
    # Organic/colloidal/bio load hits the lead elements first.
    return "RO-1-V01 (element 1, stage-1 lead)"


def _membrane_rul(score: float, fouling: float, cip_age_days: float) -> RemainingUsefulLife:
    """Preliminary membrane RUL via the shared health-slope extrapolation."""
    # Synthesize a short daily health trend from the current score and a
    # fouling-driven decline rate (points/day). This reuses the canonical
    # RUL engine rather than inventing a membrane-specific model.
    daily_decline = 0.1 + 2.0 * fouling
    trend = [min(100.0, score + daily_decline * k) for k in range(4, -1, -1)]
    rul = remaining_useful_life_days(
        health_trend=trend,
        duty_cycle=0.7,
        maintenance_age_days=cip_age_days,
        recommended_interval_days=CIP_INTERVAL_DAYS,
        comparable_asset_factor=1.0,
        failure_threshold=40.0,
    )
    return RemainingUsefulLife(
        asset_id=MEMBRANE_ASSET_ID,
        rul_days=rul.rul_days,
        lower_days=rul.lower_days,
        upper_days=rul.upper_days,
        method="membrane " + rul.method,
        basis=rul.basis,
        provenance=DataProvenance.preliminary,
    )


def compute_membrane_health(
    fouling: float,
    asset_id: str = MEMBRANE_ASSET_ID,
    cip_age_days: float = 120.0,
) -> MembraneHealth:
    """Compute preliminary membrane health from reused WQ normalized indices.

    Membrane health is derived from three normalized deterioration signals that
    the Water Quality layer already computes (so nothing is duplicated here):

    * **normalized permeate-flow decline** -- from the canonical lumped RO
      reference at the current fouling vs the clean baseline;
    * **normalized salt-passage rise** -- from :attr:`WaterQualitySnapshot.
      normalized_salt_passage` vs the clean baseline; and
    * **normalized differential-pressure rise** -- from
      :attr:`WaterQualitySnapshot.normalized_dp_bar` vs the clean baseline.

    Each signal subtracts a visible penalty from a perfect 100. Fouling severity
    (organic / colloidal / biological) is derived from the normalized dP plus the
    RO-feed UV254 / ATP / SDI; scaling severity is the worst per-compound scaling
    probability from the WQ scaling layer. A CIP is flagged when either
    normalized rise crosses its threshold, and a preliminary membrane RUL is
    projected with the shared health-slope engine.

    Args:
        fouling: Fouling/deterioration severity in ``[0, 1]``.
        asset_id: Membrane-array asset id to stamp on the result.
        cip_age_days: Days since the last clean-in-place (for the RUL estimate).

    Returns:
        A :class:`MembraneHealth` with ``provenance = preliminary``.
    """
    fouling = max(0.0, min(1.0, fouling))
    base_snap = wq.compute_snapshot(0.0)
    snap = wq.compute_snapshot(fouling)

    clean_ro = wq._ro(0.0)
    cur_ro = wq._ro(fouling)
    flow_decline_pct = _pct_rise(clean_ro.permeate_flow_m3h, cur_ro.permeate_flow_m3h)

    sp_rise_pct = _pct_rise(snap.normalized_salt_passage, base_snap.normalized_salt_passage)
    dp_rise_pct = _pct_rise(snap.normalized_dp_bar, base_snap.normalized_dp_bar)

    contributions: list[HealthContribution] = []
    if flow_decline_pct > 0.05:
        contributions.append(
            HealthContribution(
                factor="Permeate flow decline",
                delta=round(-min(40.0, 1.5 * flow_decline_pct), 2),
                detail=f"normalized permeate flow -{flow_decline_pct:.1f}% vs clean baseline",
            )
        )
    if sp_rise_pct > 0.05:
        contributions.append(
            HealthContribution(
                factor="Salt passage rise",
                delta=round(-min(40.0, 1.2 * sp_rise_pct), 2),
                detail=f"normalized salt passage +{sp_rise_pct:.1f}% vs clean baseline",
            )
        )
    if dp_rise_pct > 0.05:
        contributions.append(
            HealthContribution(
                factor="Differential pressure rise",
                delta=round(-min(30.0, 0.8 * dp_rise_pct), 2),
                detail=f"normalized dP +{dp_rise_pct:.1f}% vs clean baseline",
            )
        )

    score = max(0.0, min(100.0, 100.0 + sum(c.delta for c in contributions)))
    band = HealthBand.from_score(score)

    norm_dp_component = min(1.0, snap.normalized_dp_bar / (wq._REF_DP_BAR * 2.0))
    severity = _fouling_severity(fouling, norm_dp_component)

    # Salt-passage deterioration trend: attribute the observed normalized rise to
    # a nominal 30-day window (preliminary trend, advisory only).
    sp_trend_pct_per_day = round(sp_rise_pct / 30.0, 4)

    cleaning_required = (
        dp_rise_pct >= CIP_NORMALIZED_DP_RISE_PCT or sp_rise_pct >= CIP_NORMALIZED_SP_RISE_PCT
    )
    cleaning_reason = None
    if cleaning_required:
        reasons = []
        if dp_rise_pct >= CIP_NORMALIZED_DP_RISE_PCT:
            reasons.append(
                f"normalized dP +{dp_rise_pct:.0f}% >= {CIP_NORMALIZED_DP_RISE_PCT:.0f}% threshold"
            )
        if sp_rise_pct >= CIP_NORMALIZED_SP_RISE_PCT:
            reasons.append(
                f"normalized salt passage +{sp_rise_pct:.0f}% "
                f">= {CIP_NORMALIZED_SP_RISE_PCT:.0f}% threshold"
            )
        cleaning_reason = "CIP indicated (advisory): " + "; ".join(reasons)

    dominant_scaling = max(snap.scaling, key=lambda r: r.probability, default=None)
    scaling_stage = (
        dominant_scaling.ro_stage_at_risk.value
        if dominant_scaling and dominant_scaling.ro_stage_at_risk
        else None
    )
    vessel = _underperforming_vessel(severity, scaling_stage)

    rul = _membrane_rul(score, fouling, cip_age_days)

    return MembraneHealth(
        asset_id=asset_id,
        score=round(score, 1),
        band=band,
        normalized_permeate_flow_decline_pct=round(flow_decline_pct, 2),
        normalized_salt_passage_rise_pct=round(sp_rise_pct, 2),
        normalized_dp_rise_pct=round(dp_rise_pct, 2),
        fouling=severity,
        salt_passage_trend_pct_per_day=sp_trend_pct_per_day,
        cleaning_required=cleaning_required,
        cleaning_reason=cleaning_reason,
        underperforming_vessel=vessel,
        rul=rul,
        contributions=contributions,
        provenance=DataProvenance.preliminary,
    )
