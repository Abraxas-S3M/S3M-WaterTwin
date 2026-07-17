"""Water Quality Intelligence: synthetic ingestion + deterministic WQ engine.

This module extends the watertwin-api with the Water Quality Intelligence
capability. It:

* emits the 15 priority water-quality variables at the plant's sampling points
  (``SP-01``..``SP-20``) with ``provenance="synthetic"``;
* computes per sampling-point / stage salt rejection, salt passage, recovery,
  contaminant removal, scaling risks, normalized fouling indices and boron
  rejection using the single canonical physics engine
  (:mod:`watertwin_engineering`); and
* produces preliminary, uncertainty-bounded forecasts (permeate salinity, boron
  breakthrough, dominant scaling compound + time-to-critical, and organic/
  colloidal/biofouling risk) plus :class:`WQAlert` objects.

Everything here is **advisory and read-only**. Forecasts and risks are
preliminary engineering estimates -- never validated production predictions or
guaranteed compliance figures. Alerts carry ``approval_required=True`` and are
routed by the API through the existing recommendation + audit path. Nothing in
this module writes to any control system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from canonical_water_model import (
    ContaminantMatrixRow,
    ControlBoundary,
    DataProvenance,
    Evidence,
    QCStatus,
    RankedCause,
    RecommendationCard,
    SampleType,
    ScalingRisk,
    TreatmentStage,
    WaterQualityForecast,
    WaterQualitySample,
    WQAlert,
    now_iso,
)
from watertwin_engineering import (
    boron_rejection,
    colloidal_fouling_index,
    langelier_saturation_index,
    normalized_differential_pressure,
    normalized_salt_passage,
    ro_performance,
    silica_saturation_pct,
    sulfate_scaling_ratio,
)

# ---------------------------------------------------------------------------
# Reference plant + intake composition (synthetic).
# ---------------------------------------------------------------------------

FACILITY_ID = "S3M-DESAL-01"
TRAIN_ID = "RO-TRAIN-001"

FEED_FLOW_M3H = 500.0
FEED_PRESSURE_BAR = 60.0
MEMBRANE_AREA_M2 = 37000.0
DESIGN_RECOVERY = 0.45

#: Conversion factor from mg/L Ca2+ to mg/L as CaCO3 (100.09 / 40.078).
_CA_TO_CACO3 = 2.4973

#: Typical Arabian-Gulf seawater intake composition (synthetic reference).
INTAKE: dict[str, float] = {
    "turbidity_ntu": 2.2,
    "particle_count_per_ml": 3500.0,
    "sdi": 5.6,
    "uv254_per_cm": 0.085,
    "toc_mg_l": 1.6,
    "boron_mg_l": 5.0,
    "silica_mg_l": 1.8,
    "calcium_mg_l": 460.0,
    "magnesium_mg_l": 1400.0,
    "sulfate_mg_l": 3050.0,
    "alkalinity_mg_l_as_caco3": 140.0,
    "bromide_mg_l": 67.0,
    "free_chlorine_mg_l": 0.0,
    "orp_mv": 320.0,
    "atp_pg_ml": 320.0,
    "chlorophyll_a_ug_l": 3.2,
    "tds_mg_l": 45000.0,
    "ph": 8.1,
    "temperature_c": 26.0,
}

#: Trace scale-forming cations present in seawater but not among the 15 priority
#: online variables; documented synthetic values used for BaSO4/SrSO4 screening.
INTAKE_BARIUM_MG_L = 0.02
INTAKE_STRONTIUM_MG_L = 8.0

#: Documented approximation for the mean activity coefficient of a 2:2 (divalent-
#: divalent) electrolyte in a seawater-strength concentrate. The pure
#: :func:`sulfate_scaling_ratio` uses activity = 1 (concentration = activity);
#: at high ionic strength the true ion activities are far lower, so the engine
#: multiplies the raw ion product by ``gamma_pm^2 ~= 0.25^2`` for a
#: physically-sensible screening ratio. This is a documented approximation, not
#: a Pitzer-grade ion-interaction correction.
_DIVALENT_ACTIVITY_CORRECTION = 0.25**2

#: The 15 priority water-quality variables (human-readable -> measurement keys).
PRIORITY_VARIABLES: dict[str, list[str]] = {
    "turbidity": ["turbidity_ntu"],
    "particle_count": ["particle_count_per_ml"],
    "sdi": ["sdi"],
    "uv254": ["uv254_per_cm"],
    "toc": ["toc_mg_l"],
    "boron": ["boron_mg_l"],
    "silica": ["silica_mg_l"],
    "calcium": ["calcium_mg_l"],
    "magnesium": ["magnesium_mg_l"],
    "sulfate": ["sulfate_mg_l"],
    "alkalinity": ["alkalinity_mg_l_as_caco3"],
    "bromide": ["bromide_mg_l"],
    "free_chlorine_orp": ["free_chlorine_mg_l", "orp_mv"],
    "atp": ["atp_pg_ml"],
    "chlorophyll_a": ["chlorophyll_a_ug_l"],
}

#: Advisory limits used for compliance flags (screening only, not regulatory).
LIMITS: dict[str, float] = {
    "turbidity_ntu": 0.3,
    "sdi": 4.0,
    "boron_mg_l": 1.0,
    "tds_mg_l": 500.0,
    "toc_mg_l": 2.0,
}


@dataclass
class SamplingPointDef:
    """Static definition of a plant sampling point."""

    point_id: str
    name: str
    stage: TreatmentStage
    stream_id: str
    location: str  # one of the composition locations below
    sample_type: SampleType = SampleType.continuous


# Composition "locations" through the treatment path.
_LOCATIONS = ("intake", "post_pretreatment", "ro_feed", "permeate", "finished", "brine")

#: SP-01..SP-20 sampling points mapped to their stage / stream / location.
SAMPLING_POINTS: list[SamplingPointDef] = [
    SamplingPointDef("SP-01", "Intake screen", TreatmentStage.intake, "STR-SW-FEED", "intake"),
    SamplingPointDef("SP-02", "Post screening", TreatmentStage.screening, "STR-SW-FEED", "intake"),
    SamplingPointDef(
        "SP-03", "Media filter inlet", TreatmentStage.media_filtration, "STR-PRETREAT", "intake"
    ),
    SamplingPointDef(
        "SP-04",
        "Media filter outlet",
        TreatmentStage.media_filtration,
        "STR-PRETREAT",
        "post_pretreatment",
    ),
    SamplingPointDef(
        "SP-05",
        "Cartridge filter inlet",
        TreatmentStage.cartridge_filtration,
        "STR-PRETREAT",
        "post_pretreatment",
    ),
    SamplingPointDef(
        "SP-06",
        "Cartridge filter outlet",
        TreatmentStage.cartridge_filtration,
        "STR-PRETREAT",
        "post_pretreatment",
    ),
    SamplingPointDef("SP-07", "Dosing skid", TreatmentStage.dosing, "STR-RO-FEED", "ro_feed"),
    SamplingPointDef(
        "SP-08", "HP pump discharge", TreatmentStage.high_pressure_pumping, "STR-RO-FEED", "ro_feed"
    ),
    SamplingPointDef("SP-09", "RO stage-1 feed", TreatmentStage.ro_stage_1, "STR-RO-FEED", "ro_feed"),
    SamplingPointDef(
        "SP-10", "RO stage-1 permeate", TreatmentStage.ro_stage_1, "STR-PERMEATE", "permeate"
    ),
    SamplingPointDef(
        "SP-11", "RO stage-1 concentrate", TreatmentStage.ro_stage_1, "STR-CONCENTRATE", "brine"
    ),
    SamplingPointDef("SP-12", "RO stage-2 feed", TreatmentStage.ro_stage_2, "STR-CONCENTRATE", "brine"),
    SamplingPointDef(
        "SP-13", "RO stage-2 permeate", TreatmentStage.ro_stage_2, "STR-PERMEATE", "permeate"
    ),
    SamplingPointDef(
        "SP-14", "RO stage-2 concentrate", TreatmentStage.ro_stage_2, "STR-CONCENTRATE", "brine"
    ),
    SamplingPointDef(
        "SP-15", "Combined permeate", TreatmentStage.permeate, "STR-PERMEATE", "permeate"
    ),
    SamplingPointDef(
        "SP-16", "Remineralization inlet", TreatmentStage.remineralization, "STR-PRODUCT", "permeate"
    ),
    SamplingPointDef(
        "SP-17", "Remineralization outlet", TreatmentStage.remineralization, "STR-PRODUCT", "finished"
    ),
    SamplingPointDef("SP-18", "Disinfection", TreatmentStage.disinfection, "STR-PRODUCT", "finished"),
    SamplingPointDef(
        "SP-19", "Finished water", TreatmentStage.finished_water, "STR-PRODUCT", "finished"
    ),
    SamplingPointDef(
        "SP-20",
        "Brine discharge",
        TreatmentStage.concentrate_discharge,
        "STR-CONCENTRATE",
        "brine",
    ),
]


# ---------------------------------------------------------------------------
# Snapshot dataclass
# ---------------------------------------------------------------------------


@dataclass
class WaterQualitySnapshot:
    """A complete, self-consistent Water Quality Intelligence snapshot."""

    fouling: float
    timestamp: str
    samples: list[WaterQualitySample] = field(default_factory=list)
    stage_status: list[dict] = field(default_factory=list)
    contaminant_matrix: list[ContaminantMatrixRow] = field(default_factory=list)
    removal: list[dict] = field(default_factory=list)
    scaling: list[ScalingRisk] = field(default_factory=list)
    forecasts: list[WaterQualityForecast] = field(default_factory=list)
    alerts: list[WQAlert] = field(default_factory=list)
    # Scalar summaries used by tests + the dashboard.
    recovery: float = 0.0
    salt_rejection: float = 0.0
    salt_passage: float = 0.0
    normalized_salt_passage: float = 0.0
    normalized_dp_bar: float = 0.0
    permeate_tds_mg_l: float = 0.0
    permeate_boron_mg_l: float = 0.0


# ---------------------------------------------------------------------------
# Composition model
# ---------------------------------------------------------------------------


def _pretreatment_retention(fouling: float) -> dict[str, float]:
    """Fractional pass-through of particulate/organic load after pretreatment.

    A healthy pretreatment train removes most turbidity/particles/organics. As
    pretreatment fouls/breaks through (higher ``fouling``), more load passes to
    the RO feed. Returns the surviving fraction for each affected variable.
    """
    breakthrough = 1.0 + 2.5 * fouling  # >1 as pretreatment degrades
    return {
        "turbidity_ntu": min(1.0, 0.10 * breakthrough),
        "particle_count_per_ml": min(1.0, 0.18 * breakthrough),
        "sdi": min(1.0, 0.52 * breakthrough),
        "uv254_per_cm": min(1.0, 0.70 * breakthrough),
        "toc_mg_l": min(1.0, 0.80 * breakthrough),
        "atp_pg_ml": min(1.0, 0.45 * breakthrough),
        "chlorophyll_a_ug_l": min(1.0, 0.25 * breakthrough),
    }


def _ro(fouling: float):
    """Run the canonical lumped RO reference, de-rated by ``fouling``.

    Fouling raises the salt-transport coefficient (more salt passage) and the
    feed-channel pressure drop, which is how membrane deterioration manifests.
    """
    b_lmh = 0.15 * (1.0 + 3.0 * fouling)
    pressure_drop_bar = 1.0 * (1.0 + 1.8 * fouling)
    return ro_performance(
        feed_flow_m3h=FEED_FLOW_M3H,
        feed_tds_mg_l=INTAKE["tds_mg_l"],
        feed_pressure_bar=FEED_PRESSURE_BAR,
        membrane_area_m2=MEMBRANE_AREA_M2,
        b_lmh=b_lmh,
        temperature_c=INTAKE["temperature_c"],
        pressure_drop_bar=pressure_drop_bar,
    )


# Reference (clean-membrane) conditions for normalization, computed once.
_REF = _ro(0.0)
_REF_NDP_BAR = max(_REF.net_driving_pressure_bar, 1.0)
_REF_DP_BAR = 1.0


def _membrane_age_factor(fouling: float) -> float:
    """Boron-rejection de-rating from membrane age/fouling, in (0, 1]."""
    return max(0.80, 1.0 - 0.20 * fouling)


def _composition(fouling: float) -> dict[str, dict[str, float]]:
    """Build the per-location composition of all tracked variables."""
    ref = _ro(fouling)
    salt_passage = 1.0 - ref.salt_rejection
    cf = ref.concentrate_tds_mg_l / INTAKE["tds_mg_l"]  # concentration factor
    retention = _pretreatment_retention(fouling)
    age = _membrane_age_factor(fouling)
    ro_feed_ph = 7.8  # acid-dosed RO feed
    b_rej = boron_rejection(
        ph=ro_feed_ph, temperature_c=INTAKE["temperature_c"], membrane_age_factor=age
    )

    comp: dict[str, dict[str, float]] = {loc: {} for loc in _LOCATIONS}

    # Intake = raw values.
    comp["intake"] = dict(INTAKE)

    # Post-pretreatment: particulate/organic reduced (or broken through).
    pp = dict(INTAKE)
    for key, frac in retention.items():
        pp[key] = INTAKE[key] * frac
    pp["free_chlorine_mg_l"] = 0.0  # dechlorinated ahead of RO
    pp["orp_mv"] = 180.0
    comp["post_pretreatment"] = pp

    # RO feed: same ionic content as pretreated seawater, acid/antiscalant dosed.
    rof = dict(pp)
    rof["ph"] = 7.8
    comp["ro_feed"] = rof

    # Permeate: ions rejected per salt passage; boron per its own rejection.
    perm = {
        "tds_mg_l": ref.permeate_tds_mg_l,
        "boron_mg_l": INTAKE["boron_mg_l"] * (1.0 - b_rej),
        "silica_mg_l": INTAKE["silica_mg_l"] * salt_passage,
        "calcium_mg_l": INTAKE["calcium_mg_l"] * salt_passage,
        "magnesium_mg_l": INTAKE["magnesium_mg_l"] * salt_passage,
        "sulfate_mg_l": INTAKE["sulfate_mg_l"] * salt_passage,
        "alkalinity_mg_l_as_caco3": INTAKE["alkalinity_mg_l_as_caco3"] * salt_passage,
        "bromide_mg_l": INTAKE["bromide_mg_l"] * salt_passage,
        "turbidity_ntu": 0.05,
        "toc_mg_l": INTAKE["toc_mg_l"] * 0.05,
        "uv254_per_cm": INTAKE["uv254_per_cm"] * 0.05,
        "ph": 6.0,
        "temperature_c": INTAKE["temperature_c"],
    }
    comp["permeate"] = perm

    # Finished water: remineralized + disinfected.
    fin = dict(perm)
    fin["calcium_mg_l"] = 40.0
    fin["alkalinity_mg_l_as_caco3"] = 60.0
    fin["tds_mg_l"] = perm["tds_mg_l"] + 120.0
    fin["ph"] = 7.9
    fin["free_chlorine_mg_l"] = 0.6
    comp["finished"] = fin

    # Brine / concentrate: ions concentrated by the concentration factor.
    brine = {
        "tds_mg_l": ref.concentrate_tds_mg_l,
        "boron_mg_l": INTAKE["boron_mg_l"] * cf,
        "silica_mg_l": INTAKE["silica_mg_l"] * cf,
        "calcium_mg_l": INTAKE["calcium_mg_l"] * cf,
        "magnesium_mg_l": INTAKE["magnesium_mg_l"] * cf,
        "sulfate_mg_l": INTAKE["sulfate_mg_l"] * cf,
        "alkalinity_mg_l_as_caco3": INTAKE["alkalinity_mg_l_as_caco3"] * cf,
        "bromide_mg_l": INTAKE["bromide_mg_l"] * cf,
        "ph": 7.7,
        "temperature_c": INTAKE["temperature_c"],
    }
    comp["brine"] = brine
    return comp


# ---------------------------------------------------------------------------
# Sample generation
# ---------------------------------------------------------------------------


def generate_samples(fouling: float, timestamp: str | None = None) -> list[WaterQualitySample]:
    """Emit the 15 priority variables at each sampling point (synthetic)."""
    ts = timestamp or now_iso()
    comp = _composition(fouling)
    samples: list[WaterQualitySample] = []
    for sp in SAMPLING_POINTS:
        source = comp[sp.location]
        measurements: dict[str, float] = {}
        for keys in PRIORITY_VARIABLES.values():
            for key in keys:
                if key in source:
                    measurements[key] = round(float(source[key]), 4)
        qc = QCStatus.passed
        # Flag an obvious QC issue where SDI at the RO feed breaks through.
        if sp.location == "ro_feed" and measurements.get("sdi", 0.0) > LIMITS["sdi"]:
            qc = QCStatus.warn
        limit = None
        if sp.location in ("permeate", "finished") and "boron_mg_l" in measurements:
            limit = LIMITS["boron_mg_l"]
        samples.append(
            WaterQualitySample(
                sample_id=f"WQS-{sp.point_id}-{ts}",
                sampling_point_id=sp.point_id,
                stage=sp.stage,
                stream_id=sp.stream_id,
                timestamp=ts,
                provenance=DataProvenance.synthetic,
                measurements=measurements,
                sample_type=sp.sample_type,
                method="online analyzer" if sp.sample_type == SampleType.continuous else "grab/lab",
                detection_limit=0.01,
                limit=limit,
                qc_status=qc,
            )
        )
    return samples


# ---------------------------------------------------------------------------
# Scaling risks
# ---------------------------------------------------------------------------


def _probability_from_ratio(ratio: float, warn: float, critical: float) -> float:
    """Map a saturation ratio to a 0..1 risk probability (piecewise linear)."""
    if ratio <= warn:
        return max(0.0, 0.4 * ratio / warn)
    if ratio >= critical:
        return 1.0
    return 0.4 + 0.6 * (ratio - warn) / (critical - warn)


def compute_scaling_risks(fouling: float) -> list[ScalingRisk]:
    """Per-compound scaling risk evaluated in the RO concentrate (tail)."""
    comp = _composition(fouling)
    brine = comp["brine"]
    risks: list[ScalingRisk] = []

    # CaCO3 via LSI.
    lsi = langelier_saturation_index(
        ph=brine["ph"],
        tds_mg_l=brine["tds_mg_l"],
        calcium_mg_l_as_caco3=brine["calcium_mg_l"] * _CA_TO_CACO3,
        alkalinity_mg_l_as_caco3=brine["alkalinity_mg_l_as_caco3"],
        temperature_c=brine["temperature_c"],
    )
    caco3_prob = max(0.0, min(1.0, lsi / 2.5)) if lsi > 0 else 0.0
    risks.append(
        ScalingRisk(
            compound="CaCO3",
            saturation=round(lsi, 3),
            probability=round(caco3_prob, 3),
            ro_stage_at_risk=TreatmentStage.ro_stage_2,
            max_safe_recovery=round(max(0.35, DESIGN_RECOVERY - 0.10 * max(0.0, lsi)), 3),
            recommended_antiscalant_note=(
                "Acid/antiscalant dosing indicated; positive LSI in concentrate "
                "(preliminary — verify with concentrate titration)."
            ),
        )
    )

    # Sulfate scales.
    for compound, cation_key, cation_val in (
        ("CaSO4", "calcium_mg_l", brine["calcium_mg_l"]),
        ("BaSO4", None, INTAKE_BARIUM_MG_L * (brine["tds_mg_l"] / INTAKE["tds_mg_l"])),
        ("SrSO4", None, INTAKE_STRONTIUM_MG_L * (brine["tds_mg_l"] / INTAKE["tds_mg_l"])),
    ):
        raw_ratio = sulfate_scaling_ratio(
            cation_mg_l=cation_val, sulfate_mg_l=brine["sulfate_mg_l"], salt=compound
        )
        # Apply the documented seawater activity-coefficient approximation.
        ratio = raw_ratio * _DIVALENT_ACTIVITY_CORRECTION
        risks.append(
            ScalingRisk(
                compound=compound,
                saturation=round(ratio, 4),
                probability=round(_probability_from_ratio(ratio, warn=0.8, critical=1.5), 3),
                ro_stage_at_risk=TreatmentStage.ro_stage_2,
                max_safe_recovery=round(DESIGN_RECOVERY, 3),
                recommended_antiscalant_note=(
                    f"{compound} saturation ratio {ratio:.2f} (>1 indicates "
                    "super-saturation; preliminary, seawater activity approximation)."
                ),
            )
        )

    # Silica.
    silica_pct = silica_saturation_pct(
        silica_mg_l=brine["silica_mg_l"], temperature_c=brine["temperature_c"], ph=brine["ph"]
    )
    risks.append(
        ScalingRisk(
            compound="SiO2",
            saturation=round(silica_pct / 100.0, 4),
            probability=round(max(0.0, min(1.0, (silica_pct - 60.0) / 60.0)), 3),
            ro_stage_at_risk=TreatmentStage.ro_stage_2,
            max_safe_recovery=round(DESIGN_RECOVERY, 3),
            recommended_antiscalant_note=(
                f"Silica at {silica_pct:.0f}% of solubility in concentrate "
                "(screening estimate)."
            ),
        )
    )
    return risks


# ---------------------------------------------------------------------------
# Contaminant matrix + removal
# ---------------------------------------------------------------------------


def _removal_pct(intake: float, finished: float) -> float:
    if intake <= 0:
        return 0.0
    return round((1.0 - finished / intake) * 100.0, 2)


def compute_contaminant_matrix(fouling: float) -> list[ContaminantMatrixRow]:
    """Concentration of each contaminant across the treatment path."""
    comp = _composition(fouling)
    rows: list[ContaminantMatrixRow] = []
    tracked = [
        ("Boron", "boron_mg_l", "mg/L", LIMITS["boron_mg_l"]),
        ("Calcium", "calcium_mg_l", "mg/L", None),
        ("Magnesium", "magnesium_mg_l", "mg/L", None),
        ("Sulfate", "sulfate_mg_l", "mg/L", None),
        ("Silica", "silica_mg_l", "mg/L", None),
        ("Alkalinity", "alkalinity_mg_l_as_caco3", "mg/L as CaCO3", None),
        ("Bromide", "bromide_mg_l", "mg/L", None),
        ("TDS", "tds_mg_l", "mg/L", LIMITS["tds_mg_l"]),
        ("TOC", "toc_mg_l", "mg/L", LIMITS["toc_mg_l"]),
        ("Turbidity", "turbidity_ntu", "NTU", LIMITS["turbidity_ntu"]),
    ]
    for name, key, unit, limit in tracked:
        intake = comp["intake"].get(key)
        finished = comp["finished"].get(key)
        rows.append(
            ContaminantMatrixRow(
                contaminant=name,
                unit=unit,
                intake=_round_opt(intake),
                post_pretreatment=_round_opt(comp["post_pretreatment"].get(key)),
                ro_feed=_round_opt(comp["ro_feed"].get(key)),
                permeate=_round_opt(comp["permeate"].get(key)),
                finished=_round_opt(finished),
                brine=_round_opt(comp["brine"].get(key)),
                removal_pct=(
                    _removal_pct(intake, finished)
                    if intake is not None and finished is not None
                    else None
                ),
                limit=limit,
            )
        )
    return rows


def _round_opt(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


#: Design removal targets used for the current-vs-design-vs-predicted view.
_DESIGN_REMOVAL_PCT: dict[str, float] = {
    "Boron": 90.0,
    "TDS": 99.4,
    "Sulfate": 99.6,
    "TOC": 96.0,
    "Turbidity": 99.0,
}


def compute_removal(fouling: float) -> list[dict]:
    """Current vs design vs predicted removal, with confidence."""
    matrix = {row.contaminant: row for row in compute_contaminant_matrix(fouling)}
    out: list[dict] = []
    for name, design in _DESIGN_REMOVAL_PCT.items():
        row = matrix.get(name)
        current = row.removal_pct if row else None
        # Preliminary trend: fouling erodes removal over the coming days.
        predicted = None if current is None else round(max(0.0, current - 4.0 * fouling), 2)
        out.append(
            {
                "contaminant": name,
                "unit": "%",
                "current_pct": current,
                "design_pct": design,
                "predicted_pct": predicted,
                "confidence": round(0.7 - 0.2 * fouling, 2),
                "provenance": DataProvenance.preliminary.value,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Stage status
# ---------------------------------------------------------------------------


def compute_stage_status(fouling: float) -> list[dict]:
    """Live WQ status by stage with compliance flags."""
    comp = _composition(fouling)
    ref = _ro(fouling)
    salt_passage = 1.0 - ref.salt_rejection

    def compliance(location: str) -> list[dict]:
        checks: list[dict] = []
        source = comp[location]
        for key, limit in LIMITS.items():
            if key in source:
                value = source[key]
                checks.append(
                    {
                        "variable": key,
                        "value": round(value, 4),
                        "limit": limit,
                        "within_limit": value <= limit,
                    }
                )
        return checks

    stages = [
        ("intake", TreatmentStage.intake),
        ("post_pretreatment", TreatmentStage.cartridge_filtration),
        ("ro_feed", TreatmentStage.ro_stage_1),
        ("permeate", TreatmentStage.permeate),
        ("finished", TreatmentStage.finished_water),
        ("brine", TreatmentStage.concentrate_discharge),
    ]
    out: list[dict] = []
    for location, stage in stages:
        entry: dict = {
            "stage": stage.value,
            "location": location,
            "compliance": compliance(location),
            "provenance": DataProvenance.synthetic.value,
        }
        if location in ("permeate", "finished"):
            entry.update(
                {
                    "recovery": round(ref.recovery, 4),
                    "salt_rejection": round(ref.salt_rejection, 5),
                    "salt_passage": round(salt_passage, 5),
                }
            )
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Forecasts
# ---------------------------------------------------------------------------

#: Advisory forecast horizons and their nominal length in hours.
HORIZONS: dict[str, float] = {"1h": 1.0, "shift": 8.0, "24h": 24.0, "7d": 168.0}


def _forecast_series(
    target: str,
    unit: str,
    current: float,
    per_hour_rate: float,
    basis: str,
    rel_uncertainty: float = 0.08,
) -> list[WaterQualityForecast]:
    """Build a preliminary linear trend forecast across all horizons."""
    out: list[WaterQualityForecast] = []
    for label, hours in HORIZONS.items():
        predicted = current + per_hour_rate * hours
        # Uncertainty widens with horizon; confidence falls.
        spread = abs(predicted) * rel_uncertainty * (1.0 + hours / 48.0)
        confidence = round(max(0.3, 0.85 - 0.006 * hours), 2)
        out.append(
            WaterQualityForecast(
                target=target,
                unit=unit,
                horizon=label,
                predicted_value=round(predicted, 4),
                lower=round(predicted - spread, 4),
                upper=round(predicted + spread, 4),
                confidence=confidence,
                basis=basis,
            )
        )
    return out


def compute_forecasts(fouling: float) -> list[WaterQualityForecast]:
    """Physics/trend-based forecasts (preliminary, uncertainty-bounded)."""
    comp = _composition(fouling)
    forecasts: list[WaterQualityForecast] = []

    # Permeate salinity (TDS) creeps up as salt passage rises with fouling.
    perm_tds = comp["permeate"]["tds_mg_l"]
    forecasts += _forecast_series(
        target="permeate_salinity",
        unit="mg/L TDS",
        current=perm_tds,
        per_hour_rate=0.05 + 0.9 * fouling,
        basis="normalized salt-passage trend (preliminary)",
    )

    # Boron breakthrough as membrane ages.
    perm_boron = comp["permeate"]["boron_mg_l"]
    forecasts += _forecast_series(
        target="permeate_boron",
        unit="mg/L",
        current=perm_boron,
        per_hour_rate=0.0008 + 0.004 * fouling,
        basis="pKa speciation + membrane-age de-rating (preliminary)",
    )

    # Dominant scaling compound + time-to-critical.
    risks = compute_scaling_risks(fouling)
    dominant = max(risks, key=lambda r: r.probability)
    # Time-to-critical: closer as probability rises (bounded, screening only).
    ttc_hours = round(200.0 * (1.0 - dominant.probability) + 4.0, 1)
    forecasts.append(
        WaterQualityForecast(
            target=f"scaling_time_to_critical:{dominant.compound}",
            unit="h",
            horizon="7d",
            predicted_value=ttc_hours,
            lower=round(ttc_hours * 0.6, 1),
            upper=round(ttc_hours * 1.6, 1),
            confidence=0.45,
            basis=f"dominant scale {dominant.compound}; concentrate saturation trend (preliminary)",
        )
    )

    # Organic / colloidal / biofouling composite risk from normalized dP + ATP + UV254.
    dp_bar = _REF_DP_BAR * (1.0 + 1.8 * fouling)
    ndp = normalized_differential_pressure(dp_bar=dp_bar, flow_m3h=FEED_FLOW_M3H, ref_flow_m3h=FEED_FLOW_M3H)
    atp = comp["ro_feed"]["atp_pg_ml"]
    uv254 = comp["ro_feed"]["uv254_per_cm"]
    cfi = colloidal_fouling_index(
        sdi=comp["ro_feed"]["sdi"],
        turbidity_ntu=comp["ro_feed"]["turbidity_ntu"],
        particle_count=comp["ro_feed"]["particle_count_per_ml"],
    )
    fouling_risk = max(
        0.0,
        min(
            1.0,
            0.4 * cfi
            + 0.3 * min(1.0, ndp / (_REF_DP_BAR * 2.0))
            + 0.2 * min(1.0, atp / 400.0)
            + 0.1 * min(1.0, uv254 / 0.1),
        ),
    )
    forecasts += _forecast_series(
        target="fouling_risk",
        unit="index 0-1",
        current=fouling_risk,
        per_hour_rate=0.001 + 0.004 * fouling,
        basis="normalized dP + ATP + UV254 + colloidal index (preliminary)",
        rel_uncertainty=0.15,
    )
    return forecasts


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def compute_alerts(fouling: float) -> list[WQAlert]:
    """Generate WQ alerts; each requires operator approval before any action."""
    comp = _composition(fouling)
    alerts: list[WQAlert] = []

    dp_bar = _REF_DP_BAR * (1.0 + 1.8 * fouling)
    norm_dp = normalized_differential_pressure(
        dp_bar=dp_bar, flow_m3h=FEED_FLOW_M3H, ref_flow_m3h=FEED_FLOW_M3H
    )

    # Permeate conductivity/salinity forecast to exceed limit.
    forecasts = {f"{f.target}:{f.horizon}": f for f in compute_forecasts(fouling)}
    salinity_24h = forecasts.get("permeate_salinity:24h")
    if salinity_24h and salinity_24h.predicted_value > LIMITS["tds_mg_l"]:
        alerts.append(
            WQAlert(
                code="WQ-PERMEATE-SALINITY",
                stage=TreatmentStage.permeate,
                cause=(
                    f"Permeate salinity forecast to reach {salinity_24h.predicted_value:.0f} mg/L "
                    f"in 24h (limit {LIMITS['tds_mg_l']:.0f} mg/L)."
                ),
                horizon="24h",
                confidence=salinity_24h.confidence,
                recommended_action=(
                    "Review normalized salt passage and consider a membrane integrity check; "
                    "advisory only — operator approval required."
                ),
            )
        )

    # Elevated CaCO3 / silica scaling risk.
    for risk in compute_scaling_risks(fouling):
        if risk.probability >= 0.5:
            alerts.append(
                WQAlert(
                    code=f"WQ-SCALING-{risk.compound.upper()}",
                    stage=risk.ro_stage_at_risk,
                    cause=(
                        f"{risk.compound} scaling risk elevated in concentrate "
                        f"(saturation {risk.saturation}, p={risk.probability:.2f})."
                    ),
                    horizon="shift",
                    confidence=round(min(0.8, 0.4 + risk.probability * 0.4), 2),
                    recommended_action=(
                        f"Verify antiscalant dosing / reduce recovery below "
                        f"{risk.max_safe_recovery}; advisory only — operator approval required."
                    ),
                )
            )

    # Boron breakthrough forecast.
    boron_24h = forecasts.get("permeate_boron:24h")
    if boron_24h and boron_24h.predicted_value > LIMITS["boron_mg_l"]:
        alerts.append(
            WQAlert(
                code="WQ-BORON-BREAKTHROUGH",
                stage=TreatmentStage.permeate,
                cause=(
                    f"Permeate boron forecast to reach {boron_24h.predicted_value:.2f} mg/L in 24h "
                    f"(limit {LIMITS['boron_mg_l']:.2f} mg/L)."
                ),
                horizon="24h",
                confidence=boron_24h.confidence,
                recommended_action=(
                    "Evaluate feed pH elevation / second-pass operation; advisory only — "
                    "operator approval required."
                ),
            )
        )

    # Pretreatment breakthrough from SDI / particle rise at the RO feed.
    ro_sdi = comp["ro_feed"]["sdi"]
    if ro_sdi > LIMITS["sdi"] or norm_dp > _REF_DP_BAR * 1.5:
        alerts.append(
            WQAlert(
                code="WQ-PRETREATMENT-BREAKTHROUGH",
                stage=TreatmentStage.cartridge_filtration,
                cause=(
                    f"RO-feed SDI {ro_sdi:.1f} (limit {LIMITS['sdi']:.1f}) / normalized dP "
                    f"{norm_dp:.2f} bar rising — colloidal/organic fouling breakthrough."
                ),
                horizon="1h",
                confidence=0.6,
                recommended_action=(
                    "Inspect media/cartridge filters and coagulant dosing; advisory only — "
                    "operator approval required."
                ),
            )
        )
    return alerts


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------


def compute_snapshot(fouling: float = 0.0, timestamp: str | None = None) -> WaterQualitySnapshot:
    """Assemble a complete, self-consistent Water Quality Intelligence snapshot.

    Args:
        fouling: Fouling/deterioration severity in [0, 1]. ``0`` is a clean
            membrane + healthy pretreatment; higher values raise salt passage,
            differential pressure, scaling and fouling risk (the "membrane
            fouling scenario tick").
        timestamp: Optional ISO timestamp to stamp on the samples.

    Returns:
        A :class:`WaterQualitySnapshot`.
    """
    fouling = max(0.0, min(1.0, fouling))
    ts = timestamp or now_iso()
    ref = _ro(fouling)
    comp = _composition(fouling)
    salt_passage = 1.0 - ref.salt_rejection
    norm_sp = normalized_salt_passage(
        salt_passage=salt_passage,
        ndp_bar=max(ref.net_driving_pressure_bar, 1.0),
        temperature_c=INTAKE["temperature_c"],
        ref_ndp_bar=_REF_NDP_BAR,
    )
    dp_bar = _REF_DP_BAR * (1.0 + 1.8 * fouling)
    norm_dp = normalized_differential_pressure(
        dp_bar=dp_bar, flow_m3h=FEED_FLOW_M3H, ref_flow_m3h=FEED_FLOW_M3H
    )

    return WaterQualitySnapshot(
        fouling=fouling,
        timestamp=ts,
        samples=generate_samples(fouling, ts),
        stage_status=compute_stage_status(fouling),
        contaminant_matrix=compute_contaminant_matrix(fouling),
        removal=compute_removal(fouling),
        scaling=compute_scaling_risks(fouling),
        forecasts=compute_forecasts(fouling),
        alerts=compute_alerts(fouling),
        recovery=round(ref.recovery, 4),
        salt_rejection=round(ref.salt_rejection, 5),
        salt_passage=round(salt_passage, 5),
        normalized_salt_passage=round(norm_sp, 5),
        normalized_dp_bar=round(norm_dp, 4),
        permeate_tds_mg_l=round(ref.permeate_tds_mg_l, 3),
        permeate_boron_mg_l=round(comp["permeate"]["boron_mg_l"], 4),
    )


# ---------------------------------------------------------------------------
# Recommendation routing (pure builder; persistence/audit done by the API)
# ---------------------------------------------------------------------------


def build_wq_recommendation(
    alert: WQAlert,
    facility_id: str = FACILITY_ID,
    train_id: str = TRAIN_ID,
) -> RecommendationCard:
    """Build a canonical recommendation card from a WQ alert.

    The card is created ``pending`` with the read-only control boundary intact
    (operator approval required, no control write). The recommendation id is
    derived from the alert code so repeated snapshots are idempotent.
    """
    evidence = Evidence(
        telemetry_window="live synthetic water-quality sampling",
        assets_reviewed=[train_id],
        documents_reviewed=[],
        simulation_ids=[],
        assumptions=[
            "Preliminary water-quality model (advisory, not validated).",
            "Scaling/fouling/boron estimates use documented approximations "
            "(activity coefficients = 1; screening solubility models).",
        ],
        data_timestamp=now_iso(),
    )
    return RecommendationCard(
        recommendation_id=f"rec-wq-{alert.code.lower()}",
        packet_id=f"pkt-wq-{uuid4().hex[:12]}",
        facility_id=facility_id,
        train_id=train_id,
        treatment_stage=alert.stage,
        summary=alert.cause,
        ranked_causes=[
            RankedCause(cause=alert.cause, probability=alert.confidence, evidence=alert.code)
        ],
        recommended_action=alert.recommended_action,
        confidence=alert.confidence,
        evidence=evidence,
        control_boundary=ControlBoundary(),
        source_engine_status="water-quality: preliminary",
        created_at=now_iso(),
    )
