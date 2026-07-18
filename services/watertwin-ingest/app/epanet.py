"""Minimal, defensive EPANET ``.inp`` parser.

Parses the sections the intake flow maps onto canonical assets. It is
deliberately forgiving: a malformed line never aborts the parse — it is captured
as an *unparsed row* with a line number and a plain-language reason so the
preview can explain exactly what could not be read (never a bare "parse
failed").

This is the ONLY file format supported in this phase (per scope). It reads the
customer's declarative network description; it does not connect to, or write to,
any OT system.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# EPANET section header -> the canonical asset_type it maps onto (when it maps
# to an asset at all). Junctions/pipes/tanks/reservoirs describe topology rather
# than rated equipment, so only pumps and valves become asset-hierarchy rows.
ASSET_SECTIONS: dict[str, str] = {
    "PUMPS": "hp_pump",
    "VALVES": "control_valve",
}

# Sections whose element counts we surface in the preview even if they do not
# become asset rows.
COUNTED_SECTIONS: tuple[str, ...] = (
    "JUNCTIONS",
    "RESERVOIRS",
    "TANKS",
    "PIPES",
    "PUMPS",
    "VALVES",
)


@dataclass
class NetworkElement:
    element_id: str
    section: str
    fields: list[str]
    line: int


@dataclass
class UnparsedLine:
    line: int
    section: str
    raw: str
    reason: str


@dataclass
class ParsedNetwork:
    title: str = ""
    elements: dict[str, list[NetworkElement]] = field(default_factory=dict)
    unparsed: list[UnparsedLine] = field(default_factory=list)

    def by_section(self, section: str) -> list[NetworkElement]:
        return self.elements.get(section, [])


def looks_like_epanet(content: str) -> tuple[bool, float, str]:
    """Cheap sniff: does this text look like an EPANET ``.inp`` file?

    Returns ``(is_epanet, confidence, detail)``. Confidence rises with the
    number of recognised EPANET section headers present.
    """
    upper = content.upper()
    markers = ["[JUNCTIONS]", "[PIPES]", "[RESERVOIRS]", "[TANKS]", "[PUMPS]", "[TITLE]"]
    hits = [m for m in markers if m in upper]
    if "[END]" in upper:
        hits.append("[END]")
    if not hits:
        return False, 0.1, "No EPANET section headers were found."
    confidence = min(0.5 + 0.1 * len(hits), 0.99)
    detail = f"Recognised EPANET sections: {', '.join(sorted(set(hits)))}."
    return True, confidence, detail


def _strip_comment(line: str) -> str:
    idx = line.find(";")
    return line[:idx] if idx >= 0 else line


def parse_inp(content: str) -> ParsedNetwork:
    """Parse an EPANET ``.inp`` file into recognised elements + unparsed lines."""
    network = ParsedNetwork()
    section: str | None = None
    title_parts: list[str] = []

    for lineno, raw in enumerate(content.splitlines(), start=1):
        stripped = _strip_comment(raw).strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().upper()
            continue
        if section is None:
            continue
        if section == "TITLE":
            title_parts.append(stripped)
            continue
        if section not in COUNTED_SECTIONS:
            # Sections we do not model (e.g. [COORDINATES], [OPTIONS]) are ignored.
            continue

        parts = stripped.split()
        if not parts:
            continue
        element_id = parts[0]
        rest = parts[1:]

        # Pumps and valves must reference two end nodes to be a usable asset.
        if section in ("PUMPS", "VALVES") and len(rest) < 2:
            network.unparsed.append(
                UnparsedLine(
                    line=lineno,
                    section=f"[{section}]",
                    raw=raw.strip(),
                    reason=(
                        f"A {section[:-1].lower()} needs an id and two end nodes; "
                        f"found {len(parts)} field(s)."
                    ),
                )
            )
            continue

        network.elements.setdefault(section, []).append(
            NetworkElement(element_id=element_id, section=section, fields=rest, line=lineno)
        )

    network.title = " ".join(title_parts).strip()
    return network
