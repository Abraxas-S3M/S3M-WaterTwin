"""Document parsers for the watertwin-ingest service (text extraction only)."""

from .document import (
    Chunk,
    ParsedDocument,
    ParseStatus,
    SUPPORTED_EXTENSIONS,
    chunk_text,
    parse_document,
)

__all__ = [
    "Chunk",
    "ParsedDocument",
    "ParseStatus",
    "SUPPORTED_EXTENSIONS",
    "chunk_text",
    "parse_document",
]
"""Parser registry, content sniffing, and the XXE/unsafe-content guard.

Uploaded files are untrusted customer input. Before a file is ever handed to a
worker we:

* **sniff** a best-effort format from its content (advisory only — a human must
  confirm the classification via the ``classify`` endpoint), and
* **reject** any file that carries an XML external-entity / DTD attack. EPANET
  ``.inp`` files are plain text and never XML, so an XML payload here is either a
  misclassification or an attack; we parse the XML-looking payload with
  :mod:`defusedxml` purely to detect and refuse external-entity / DTD abuse.
"""Bulk-import parsers.

Each parser reads a customer-supplied file, resolves it against configuration,
writes the result to staging, and returns a result object carrying an approval
proposal plus everything that could not be parsed (reported, never guessed or
silently repaired).
"""Template-driven spreadsheet parsers for the workbench importer.

Each parser exposes the same tiny surface -- ``COLUMNS`` (its published column
contract), ``parse(data, filename)`` (producing a reviewable
:class:`~app.parsers.tabular.ParseReport`) and ``template_csv()`` (the downloadable
template rendered from the very same contract, so template and parser can never
drift). The shared reading/validation engine and the reusable formula-injection
escape helper live in :mod:`app.parsers.tabular`.
"""

from __future__ import annotations

from defusedxml import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden
from defusedxml.ElementTree import fromstring as _defused_fromstring

from .base import (
    CANONICAL_UNITS,
    ParsedEntity,
    Parser,
    ParseResult,
    ParseScope,
    ParseStats,
    ParseStatus,
    ParseWarning,
    UnparsedItem,
)
from .epanet import EpanetParser

__all__ = [
    "CANONICAL_UNITS",
    "EpanetParser",
    "ParseResult",
    "ParseScope",
    "ParseStats",
    "ParseStatus",
    "ParseWarning",
    "ParsedEntity",
    "Parser",
    "UnknownFormatError",
    "UnparsedItem",
    "UnsafeContentError",
    "get_parser",
    "guard_unsafe_content",
    "sniff_format",
    "supported_formats",
]

#: Registry mapping a confirmed ``file_format`` to its parser class.
_REGISTRY: dict[str, type[Parser]] = {
    EpanetParser.file_format: EpanetParser,
}


class UnknownFormatError(ValueError):
    """Raised when no parser is registered for a requested ``file_format``."""


class UnsafeContentError(ValueError):
    """Raised when an upload carries an XML external-entity / DTD attack."""


def supported_formats() -> list[str]:
    """Return the sorted list of confirmable file formats."""
    return sorted(_REGISTRY)


def get_parser(file_format: str) -> Parser:
    """Return a parser instance for a confirmed ``file_format``."""
    try:
        parser_cls = _REGISTRY[file_format]
    except KeyError as exc:
        raise UnknownFormatError(
            f"no parser for format '{file_format}'; known: {supported_formats()}"
        ) from exc
    return parser_cls()


def _as_text(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


def _looks_like_xml(text: str) -> bool:
    head = text.lstrip()[:4096].lower()
    return (
        head.startswith("<?xml")
        or head.startswith("<")
        or "<!doctype" in head
        or "<!entity" in head
    )


def guard_unsafe_content(raw: bytes | str) -> None:
    """Reject an upload that carries an XML external-entity / DTD attack.

    No-op for a normal (non-XML) EPANET ``.inp``. When the payload looks like
    XML we parse it with :mod:`defusedxml`, which refuses DTDs, external entities
    and external references; any such construct raises :class:`UnsafeContentError`.
    """
    text = _as_text(raw)
    if not _looks_like_xml(text):
        return
    try:
        _defused_fromstring(text)
    except (DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden) as exc:
        raise UnsafeContentError(
            f"rejected XML external-entity/DTD content: {type(exc).__name__}"
        ) from exc
    except Exception:
        # Not valid XML (and not a forbidden-entity attack). An EPANET .inp that
        # merely happens to start with '<' is handled by the EPANET parser, which
        # will route the unreadable lines to ``unparsed`` rather than crash.
        return


def sniff_format(raw: bytes | str) -> str | None:
    """Best-effort format guess from file content (advisory; human confirms).

    Returns a key from :func:`supported_formats` or ``None`` when unrecognized.
    This is only a hint for the operator — the ``classify`` endpoint requires a
    human to confirm the format before any parse runs.
    """
    text = _as_text(raw)
    upper = text.upper()
    epanet_markers = ("[JUNCTIONS]", "[PIPES]", "[RESERVOIRS]", "[TANKS]", "[OPTIONS]", "[TITLE]")
    if sum(marker in upper for marker in epanet_markers) >= 2:
        return EpanetParser.file_format
    return None
from .base import ParseWarning, UnparsedRecord
from .gis import GisParseError, GisParseResult, parse_gis
from .historian import HistorianParseError, HistorianParseResult, parse_historian

__all__ = [
    "GisParseError",
    "GisParseResult",
    "HistorianParseError",
    "HistorianParseResult",
    "ParseWarning",
    "UnparsedRecord",
    "parse_gis",
    "parse_historian",
]
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
