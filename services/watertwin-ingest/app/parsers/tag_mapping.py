"""Templated OT tag-mapping importer.

Parses a customer-supplied tag map (OT tag -> canonical asset, with linear
scaling) into reviewable records. The linear transform is ``canonical = raw *
scale + offset``. Units are taken from an explicit, required ``unit`` column --
never inferred -- and ``scale``/``offset``/``deadband`` are range-checked against
``watertwin_engineering.SPECIFICATION_RANGES`` so an implausible scale or a
negative deadband surfaces as a validation error in the review diff.

This importer only *describes* how to interpret inbound OT tags; it never opens a
connection to, or writes to, any OT/SCADA/PLC system. Every emitted record is
stamped ``provenance = "customer_supplied"``.
"""

from __future__ import annotations

from .tabular import ColumnSpec, ParseReport, parse_table, render_template_csv

__all__ = ["PROVENANCE", "KIND", "COLUMNS", "parse", "template_csv"]

#: Tag maps are provided by the customer describing their own OT namespace.
PROVENANCE = "customer_supplied"
KIND = "tag_mapping"

#: The published tag-mapping column contract. Order defines the template layout.
COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec(
        name="ot_tag", label="OT tag", required=True, kind="string",
        aliases=("tag", "customer_tag", "source_tag", "point", "nodeid", "node_id"),
        example="PLC1.HPP01.FLOW", description="Customer OT/SCADA tag or point name.",
    ),
    ColumnSpec(
        name="asset_id", label="Canonical asset ID", required=True, kind="string",
        aliases=("asset", "canonical_asset_id", "asset_tag", "equipment_id"),
        example="AST-HPP-01", description="Canonical asset this tag belongs to.",
    ),
    ColumnSpec(
        name="measurement_type", label="Measurement type", required=True, kind="string",
        aliases=("measurement", "metric", "measurement_kind", "type"),
        example="flow", description="Measurement/metric this tag reports (e.g. flow, pressure).",
    ),
    ColumnSpec(
        name="unit", label="Unit", required=True, kind="string",
        aliases=("engineering_unit", "uom", "units"),
        example="m3/h", description="Explicit engineering unit of the raw value (required).",
    ),
    ColumnSpec(
        name="scale", label="Scale", required=False, kind="number",
        unit="dimensionless", range_key="tag_mapping.scale", default=1.0,
        aliases=("scale_factor", "gain", "multiplier"),
        example="1.0", description="Linear scale (canonical = raw * scale + offset).",
    ),
    ColumnSpec(
        name="offset", label="Offset", required=False, kind="number",
        unit="engineering units", range_key="tag_mapping.offset", default=0.0,
        aliases=("bias", "zero_offset"),
        example="0.0", description="Linear offset (canonical = raw * scale + offset).",
    ),
    ColumnSpec(
        name="deadband", label="Deadband", required=False, kind="number",
        unit="engineering units", range_key="tag_mapping.deadband",
        aliases=("dead_band", "cov_deadband", "change_of_value"),
        example="0.5", description="Change-of-value deadband (never negative).",
    ),
)


def parse(data: bytes, filename: str, *, encoding: str | None = None) -> ParseReport:
    """Parse a tag-mapping CSV/XLSX into a :class:`ParseReport`."""
    return parse_table(
        data, filename, COLUMNS, kind=KIND, provenance=PROVENANCE, encoding=encoding
    )


def template_csv() -> str:
    """Return the downloadable tag-mapping template rendered from :data:`COLUMNS`."""
    return render_template_csv(COLUMNS)
