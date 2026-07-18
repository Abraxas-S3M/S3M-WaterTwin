"""Templated laboratory-method importer.

Parses a customer-supplied catalogue of lab analytical methods (which analyte is
measured at which sample point, by which method, in which unit, with what
detection/quantitation limits) into reviewable records.

Units come from an explicit, required ``unit`` column -- never inferred -- and the
limit-of-detection (LOD) and limit-of-quantitation (LOQ) are range-checked
against ``watertwin_engineering.SPECIFICATION_RANGES`` (never negative). A LOQ
below its LOD is also flagged, because quantitation cannot be more sensitive than
detection. Every emitted record is stamped ``provenance = "customer_supplied"``.
"""

from __future__ import annotations

from .tabular import ColumnSpec, ParseReport, parse_table, render_template_csv

__all__ = ["PROVENANCE", "KIND", "COLUMNS", "parse", "template_csv"]

#: Lab method catalogues are supplied by the customer's laboratory.
PROVENANCE = "customer_supplied"
KIND = "lab"

#: The published lab-method column contract. Order defines the template layout.
COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec(
        name="sample_point", label="Sample point", required=True, kind="string",
        aliases=("sampling_point", "point", "location", "sample_location"),
        example="RO-PERMEATE", description="Sample point / location identifier.",
    ),
    ColumnSpec(
        name="parameter", label="Parameter", required=True, kind="string",
        aliases=("analyte", "determinand", "measurand"),
        example="Boron", description="Analyte / parameter measured.",
    ),
    ColumnSpec(
        name="method", label="Method", required=True, kind="string",
        aliases=("method_id", "technique", "test_method", "standard_method"),
        example="ICP-MS (EPA 200.8)", description="Analytical method or standard reference.",
    ),
    ColumnSpec(
        name="unit", label="Unit", required=True, kind="string",
        aliases=("engineering_unit", "uom", "units"),
        example="mg/L", description="Explicit reporting unit (required).",
    ),
    ColumnSpec(
        name="lod", label="LOD", required=False, kind="number",
        unit="method unit", range_key="lab.lod",
        aliases=("limit_of_detection", "detection_limit", "mdl"),
        example="0.02", description="Limit of detection in the reporting unit.",
    ),
    ColumnSpec(
        name="loq", label="LOQ", required=False, kind="number",
        unit="method unit", range_key="lab.loq",
        aliases=("limit_of_quantitation", "quantitation_limit", "reporting_limit"),
        example="0.05", description="Limit of quantitation in the reporting unit.",
    ),
)


def parse(data: bytes, filename: str, *, encoding: str | None = None) -> ParseReport:
    """Parse a lab-method CSV/XLSX into a :class:`ParseReport`.

    In addition to the shared range checks, a row whose LOQ is below its LOD is
    rejected (quantitation cannot be more sensitive than detection).
    """
    report = parse_table(
        data, filename, COLUMNS, kind=KIND, provenance=PROVENANCE, encoding=encoding
    )
    _flag_loq_below_lod(report)
    return report


def _flag_loq_below_lod(report: ParseReport) -> None:
    """Reject any imported record whose LOQ is below its LOD."""
    kept: list[dict] = []
    for record in report.records:
        lod = record.get("lod")
        loq = record.get("loq")
        if lod is not None and loq is not None and loq < lod:
            report.add_error(
                row=int(record.get("_row", 1)),
                column="loq",
                message=(
                    f"LOQ ({loq}) is below LOD ({lod}); quantitation cannot be more "
                    "sensitive than detection"
                ),
            )
            continue
        kept.append(record)
    report.records = kept


def template_csv() -> str:
    """Return the downloadable lab-method template rendered from :data:`COLUMNS`."""
    return render_template_csv(COLUMNS)
