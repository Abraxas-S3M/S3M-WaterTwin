"""Template-driven spreadsheet parsers for the workbench importer.

Each parser exposes the same tiny surface -- ``COLUMNS`` (its published column
contract), ``parse(data, filename)`` (producing a reviewable
:class:`~app.parsers.tabular.ParseReport`) and ``template_csv()`` (the downloadable
template rendered from the very same contract, so template and parser can never
drift). The shared reading/validation engine and the reusable formula-injection
escape helper live in :mod:`app.parsers.tabular`.
"""

from __future__ import annotations

import os
from types import ModuleType

from . import equipment, lab, tabular, tag_mapping
from .tabular import (
    ColumnSpec,
    IngestError,
    ParseReport,
    RowIssue,
    escape_formula,
    parse_table,
    render_template_csv,
)

__all__ = [
    "ColumnSpec",
    "IngestError",
    "ParseReport",
    "RowIssue",
    "escape_formula",
    "parse_table",
    "render_template_csv",
    "equipment",
    "lab",
    "tabular",
    "tag_mapping",
    "PARSERS",
    "TEMPLATE_FILENAMES",
    "TEMPLATES_DIR",
    "get_parser",
    "render_all_templates",
    "write_templates",
]

#: Registry of the shipped parsers, keyed by their ``KIND``.
PARSERS: dict[str, ModuleType] = {
    equipment.KIND: equipment,
    tag_mapping.KIND: tag_mapping,
    lab.KIND: lab,
}

#: Downloadable template filename for each parser ``KIND``.
TEMPLATE_FILENAMES: dict[str, str] = {
    equipment.KIND: "equipment_template.csv",
    tag_mapping.KIND: "tag_mapping_template.csv",
    lab.KIND: "lab_methods_template.csv",
}

#: Directory holding the committed, downloadable template CSVs.
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")


def get_parser(kind: str) -> ModuleType:
    """Return the parser module for ``kind`` (KeyError if unknown)."""
    return PARSERS[kind]


def render_all_templates() -> dict[str, str]:
    """Render every template CSV from its parser contract, keyed by filename."""
    return {
        TEMPLATE_FILENAMES[kind]: parser.template_csv() for kind, parser in PARSERS.items()
    }


def write_templates(directory: str = TEMPLATES_DIR) -> list[str]:
    """Render and write all templates to ``directory``; return the paths written."""
    os.makedirs(directory, exist_ok=True)
    written: list[str] = []
    for filename, content in render_all_templates().items():
        path = os.path.join(directory, filename)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        written.append(path)
    return written
