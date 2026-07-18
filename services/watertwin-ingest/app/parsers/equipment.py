"""Templated equipment-specification importer.

Parses a vendor/nameplate equipment sheet into reviewable records. The published
column contract is the single source of truth for both the parser and the
downloadable template, so the two can never drift.

Numeric nameplate values are range-checked against
``watertwin_engineering.SPECIFICATION_RANGES`` -- a negative NPSHr, an efficiency
above ``1.0`` or an implausible head are surfaced as validation errors in the
review diff rather than silently imported. Units are fixed by the documented
template defaults (embedded in each numeric header); values are never unit-
inferred.

Every emitted record is stamped ``provenance = "vendor_specified"``.
"""

from __future__ import annotations

from .tabular import ColumnSpec, ParseReport, parse_table, render_template_csv

__all__ = ["PROVENANCE", "KIND", "COLUMNS", "parse", "template_csv"]

#: Records produced here describe manufacturer-published (nameplate) data.
PROVENANCE = "vendor_specified"
KIND = "equipment"

#: The published equipment column contract. Order defines the template layout.
COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec(
        name="asset_id", label="Asset ID", required=True, kind="string",
        aliases=("asset", "asset_tag", "tag", "equipment_id"),
        example="AST-HPP-01", description="Canonical asset identifier.",
    ),
    ColumnSpec(
        name="name", label="Name", required=True, kind="string",
        aliases=("equipment_name", "description"),
        example="High-pressure pump 01", description="Human-readable equipment name.",
    ),
    ColumnSpec(
        name="type", label="Type", required=True, kind="string",
        aliases=("equipment_type", "asset_type", "kind"),
        example="hp_pump", description="Equipment type (e.g. hp_pump, motor, erd).",
    ),
    ColumnSpec(
        name="manufacturer", label="Manufacturer", required=False, kind="string",
        aliases=("make", "vendor", "oem"),
        example="Acme Pumps", description="Original equipment manufacturer.",
    ),
    ColumnSpec(
        name="model", label="Model", required=False, kind="string",
        aliases=("model_number", "part_number"),
        example="HPX-500", description="Manufacturer model designation.",
    ),
    ColumnSpec(
        name="rated_flow_m3h", label="Rated flow", required=False, kind="number",
        unit="m3/h", range_key="equipment.rated_flow_m3h",
        aliases=("rated_flow", "flow", "rated_flow_m3_h", "design_flow"),
        example="420", description="Rated volumetric flow in m3/h.",
    ),
    ColumnSpec(
        name="rated_head_m", label="Rated head", required=False, kind="number",
        unit="m", range_key="equipment.rated_head_m",
        aliases=("rated_head", "head", "design_head"),
        example="620", description="Rated head in metres.",
    ),
    ColumnSpec(
        name="rated_power_kw", label="Rated power", required=False, kind="number",
        unit="kW", range_key="equipment.rated_power_kw",
        aliases=("rated_power", "power", "motor_power", "shaft_power"),
        example="850", description="Rated shaft/motor power in kW.",
    ),
    ColumnSpec(
        name="speed_rpm", label="Speed", required=False, kind="number",
        unit="rpm", range_key="equipment.speed_rpm",
        aliases=("rated_speed", "speed", "rated_speed_rpm", "rpm"),
        example="2980", description="Rated rotational speed in rpm.",
    ),
    ColumnSpec(
        name="efficiency", label="Efficiency", required=False, kind="number",
        unit="fraction", range_key="equipment.efficiency_fraction",
        aliases=("bep_efficiency", "rated_efficiency", "eff"),
        example="0.82", description="Best-efficiency-point efficiency as a fraction 0-1.",
    ),
    ColumnSpec(
        name="npshr_m", label="NPSHr", required=False, kind="number",
        unit="m", range_key="equipment.npshr_m",
        aliases=("npshr", "npsh_required", "npsh_r", "npsh_required_m"),
        example="3.5", description="Net positive suction head required, metres.",
    ),
    ColumnSpec(
        name="install_date", label="Install date", required=False, kind="date",
        aliases=("installation_date", "commissioned", "commission_date"),
        example="2021-06-15", description="Installation/commissioning date (YYYY-MM-DD).",
    ),
)


def parse(data: bytes, filename: str, *, encoding: str | None = None) -> ParseReport:
    """Parse an equipment-specification CSV/XLSX into a :class:`ParseReport`."""
    return parse_table(
        data, filename, COLUMNS, kind=KIND, provenance=PROVENANCE, encoding=encoding
    )


def template_csv() -> str:
    """Return the downloadable equipment template rendered from :data:`COLUMNS`."""
    return render_template_csv(COLUMNS)
