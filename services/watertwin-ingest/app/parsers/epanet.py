"""EPANET 2.2 ``.inp`` parser (dependency-light, units-aware, partial-success).

Why a bespoke plain-text parser rather than WNTR?

``services/hydraulic-sim`` depends on ``wntr`` (which wraps the EPANET solver),
but WNTR is the wrong tool for *ingesting untrusted customer files*:

* WNTR **raises** on malformed input — the exact opposite of the "partial
  success is normal, never crash" contract this ingest path requires.
* WNTR does not surface per-entity **source line numbers** or plain-language
  reasons for the parts it could not read, both of which a human reviewer needs.
* Pulling the WNTR/EPANET + numpy/pandas/networkx scientific stack into a
  hardened, network-isolated sandbox worker is heavy and needless for a
  line-oriented text format.

So this module is a focused, standard-library-only reader for the sections the
canonical model cares about. It records a source line number for every entity,
normalizes hydraulic quantities to the canonical SI units, and — when the
source units are absent or ambiguous — refuses to guess: it warns and routes the
affected fields to ``unparsed``.
"""

from __future__ import annotations

import time

from .base import (
    ParsedEntity,
    Parser,
    ParseResult,
    ParseScope,
    ParseStatus,
    ParseWarning,
    UnparsedItem,
)

# EPANET flow-unit keyword -> factor converting that unit to m3/h.
_FLOW_TO_M3H: dict[str, float] = {
    "CFS": 101.94074,  # cubic feet / second
    "GPM": 0.2271247,  # US gallons / minute
    "MGD": 157.72549,  # million US gallons / day
    "IMGD": 189.42041,  # million imperial gallons / day
    "AFD": 51.395075,  # acre-feet / day
    "LPS": 3.6,  # litres / second
    "LPM": 0.06,  # litres / minute
    "MLD": 41.666667,  # megalitres / day
    "CMH": 1.0,  # cubic metres / hour (already canonical)
    "CMD": 1.0 / 24.0,  # cubic metres / day
}

# US-customary flow units imply feet for length/head and inches for diameter;
# the SI flow units imply metres and millimetres.
_US_UNITS = frozenset({"CFS", "GPM", "MGD", "IMGD", "AFD"})
_SI_UNITS = frozenset({"LPS", "LPM", "MLD", "CMH", "CMD"})

_FT_TO_M = 0.3048
_IN_TO_MM = 25.4

_KNOWN_SECTIONS = frozenset(
    {
        "TITLE",
        "JUNCTIONS",
        "RESERVOIRS",
        "TANKS",
        "PIPES",
        "PUMPS",
        "VALVES",
        "CURVES",
        "PATTERNS",
        "COORDINATES",
        "OPTIONS",
    }
)

# Structural EPANET sections we knowingly skip (not network entities, and not an
# error). They are recorded in stats.sections_seen but produce no warning.
_IGNORED_SECTIONS = frozenset(
    {
        "END",
        "TAGS",
        "DEMANDS",
        "STATUS",
        "CONTROLS",
        "RULES",
        "ENERGY",
        "EMITTERS",
        "QUALITY",
        "SOURCES",
        "REACTIONS",
        "MIXING",
        "TIMES",
        "REPORT",
        "VERTICES",
        "LABELS",
        "BACKDROP",
    }
)


class _UnitSystem:
    """Resolved unit system for a file, with normalizing converters.

    When the source units are unknown (``valid`` is False) every converter
    returns ``None`` — the caller then routes the affected field to ``unparsed``
    instead of guessing.
    """

    def __init__(self, flow_units: str | None) -> None:
        self.raw = flow_units
        self.valid = flow_units in _FLOW_TO_M3H
        self.is_us = flow_units in _US_UNITS if self.valid else False

    def flow_m3h(self, value: float) -> float | None:
        if not self.valid:
            return None
        return value * _FLOW_TO_M3H[self.raw]

    def length_m(self, value: float) -> float | None:
        if not self.valid:
            return None
        return value * (_FT_TO_M if self.is_us else 1.0)

    def diameter_mm(self, value: float) -> float | None:
        if not self.valid:
            return None
        return value * (_IN_TO_MM if self.is_us else 1.0)


class _Record:
    __slots__ = ("line", "raw", "section", "tokens")

    def __init__(self, line: int, section: str, tokens: list[str], raw: str) -> None:
        self.line = line
        self.section = section
        self.tokens = tokens
        self.raw = raw


def _to_float(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


class EpanetParser(Parser):
    """Parse an EPANET 2.2 ``.inp`` into normalized, canonical-unit entities."""

    file_format = "epanet"
    name = "epanet-2.2-plaintext"

    def parse(self, path: str, scope: ParseScope) -> ParseResult:
        started = time.monotonic()
        result = ParseResult(status=ParseStatus.parsed, parser=self.name)
        try:
            self._parse_into(path, scope, result)
        except Exception as exc:
            # Defense in depth: any unexpected failure becomes a clean partial
            # result rather than a raised exception. The worker also isolates us.
            result.warnings.append(
                ParseWarning(message=f"internal parser error, output may be incomplete: {exc}")
            )
        return result.finalize(duration_s=time.monotonic() - started)

    # -- reading ------------------------------------------------------------

    def _parse_into(self, path: str, scope: ParseScope, result: ParseResult) -> None:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        result.stats.total_lines = len(lines)

        records, sections_seen = self._scan(lines, result)
        result.stats.sections_seen = sorted(sections_seen)

        units = self._resolve_units(records, result)
        result.stats.source_units = units.raw

        selected = {s.upper() for s in scope.sections} if scope.sections else None
        coords = self._collect_coordinates(records, selected)

        # Deterministic emission order so entity ids and counts are stable.
        self._emit_nodes(records, result, units, coords, selected)
        self._emit_links(records, result, units, selected)
        self._emit_curves(records, result, selected)
        self._emit_patterns(records, result, selected)

    def _scan(
        self, lines: list[str], result: ParseResult
    ) -> tuple[list[_Record], set[str]]:
        records: list[_Record] = []
        sections_seen: set[str] = set()
        section: str | None = None
        warned_unknown: set[str] = set()
        for idx, raw_line in enumerate(lines, start=1):
            line = raw_line.split(";", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().upper()
                sections_seen.add(section)
                if (
                    section not in _KNOWN_SECTIONS
                    and section not in _IGNORED_SECTIONS
                    and section not in warned_unknown
                ):
                    warned_unknown.add(section)
                    result.warnings.append(
                        ParseWarning(
                            message=(
                                f"unknown section [{section}] ignored (not silently "
                                "dropped; no entities extracted from it)"
                            ),
                            section=section,
                            line=idx,
                        )
                    )
                continue
            if section is None:
                continue
            records.append(_Record(idx, section, line.split(), raw_line.rstrip("\n")))
        return records, sections_seen

    def _resolve_units(self, records: list[_Record], result: ParseResult) -> _UnitSystem:
        flow_units: str | None = None
        for rec in records:
            if rec.section != "OPTIONS" or not rec.tokens:
                continue
            if rec.tokens[0].upper() == "UNITS" and len(rec.tokens) >= 2:
                flow_units = rec.tokens[1].upper()
                break
        units = _UnitSystem(flow_units)
        if flow_units is None:
            result.warnings.append(
                ParseWarning(
                    message=(
                        "[OPTIONS] UNITS is absent; hydraulic quantities cannot be "
                        "normalized and are routed to unparsed (units are never guessed)"
                    ),
                    section="OPTIONS",
                )
            )
        elif not units.valid:
            result.warnings.append(
                ParseWarning(
                    message=(
                        f"[OPTIONS] UNITS '{flow_units}' is not a recognized EPANET flow "
                        "unit; hydraulic quantities are routed to unparsed (never guessed)"
                    ),
                    section="OPTIONS",
                )
            )
        return units

    def _collect_coordinates(
        self, records: list[_Record], selected: set[str] | None
    ) -> dict[str, tuple[float, float]]:
        if selected is not None and "COORDINATES" not in selected:
            return {}
        coords: dict[str, tuple[float, float]] = {}
        for rec in records:
            if rec.section != "COORDINATES" or len(rec.tokens) < 3:
                continue
            x = _to_float(rec.tokens[1])
            y = _to_float(rec.tokens[2])
            if x is not None and y is not None:
                coords[rec.tokens[0]] = (x, y)
        return coords

    # -- unit-bearing field helper -----------------------------------------

    def _norm(
        self,
        result: ParseResult,
        rec: _Record,
        entity_id: str,
        field: str,
        raw_value: str,
        kind: str,
        units: _UnitSystem,
    ) -> float | None:
        """Normalize one unit-bearing token, or route it to ``unparsed``.

        Returns the canonical value, or ``None`` (and records an
        :class:`UnparsedItem`) when the value is missing/non-numeric or the
        source units are unknown.
        """
        value = _to_float(raw_value)
        if value is None:
            result.unparsed.append(
                UnparsedItem(
                    line=rec.line,
                    section=rec.section,
                    entity_id=entity_id,
                    field=field,
                    raw=rec.raw,
                    reason=f"missing or non-numeric value for '{field}'",
                )
            )
            return None
        converter = {
            "flow": units.flow_m3h,
            "length": units.length_m,
            "diameter": units.diameter_mm,
        }[kind]
        normalized = converter(value)
        if normalized is None:
            result.unparsed.append(
                UnparsedItem(
                    line=rec.line,
                    section=rec.section,
                    entity_id=entity_id,
                    field=field,
                    raw=rec.raw,
                    reason=(
                        f"source units unknown/ambiguous; cannot normalize hydraulic "
                        f"field '{field}' (units are never guessed)"
                    ),
                )
            )
            return None
        return normalized

    def _want(self, selected: set[str] | None, section: str) -> bool:
        return selected is None or section in selected

    # -- entity emission ----------------------------------------------------

    def _emit_nodes(
        self,
        records: list[_Record],
        result: ParseResult,
        units: _UnitSystem,
        coords: dict[str, tuple[float, float]],
        selected: set[str] | None,
    ) -> None:
        for rec in records:
            section = rec.section
            if section not in {"JUNCTIONS", "RESERVOIRS", "TANKS"}:
                continue
            if not self._want(selected, section) or not rec.tokens:
                continue
            entity_id = rec.tokens[0]
            fields: dict[str, object] = {}
            if section == "JUNCTIONS":
                entity_type = "junction"
                fields["elevation_m"] = self._norm(
                    result, rec, entity_id, "elevation_m", self._tok(rec, 1), "length", units
                )
                if len(rec.tokens) > 2:
                    fields["base_demand_m3h"] = self._norm(
                        result, rec, entity_id, "base_demand_m3h", self._tok(rec, 2), "flow", units
                    )
                if len(rec.tokens) > 3:
                    fields["demand_pattern"] = rec.tokens[3]
            elif section == "RESERVOIRS":
                entity_type = "reservoir"
                fields["head_m"] = self._norm(
                    result, rec, entity_id, "head_m", self._tok(rec, 1), "length", units
                )
                if len(rec.tokens) > 2:
                    fields["head_pattern"] = rec.tokens[2]
            else:
                entity_type = "tank"
                for field, idx in (
                    ("elevation_m", 1),
                    ("init_level_m", 2),
                    ("min_level_m", 3),
                    ("max_level_m", 4),
                ):
                    fields[field] = self._norm(
                        result, rec, entity_id, field, self._tok(rec, idx), "length", units
                    )
                fields["diameter_m"] = self._norm(
                    result, rec, entity_id, "diameter_m", self._tok(rec, 5), "length", units
                )
                if len(rec.tokens) > 6:
                    min_vol = _to_float(rec.tokens[6])
                    if min_vol is not None:
                        fields["min_volume_m3"] = min_vol
            if entity_id in coords:
                x, y = coords[entity_id]
                fields["coord_x"] = x
                fields["coord_y"] = y
            result.entities.append(
                ParsedEntity(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    name=entity_id,
                    fields={k: v for k, v in fields.items() if v is not None},
                    source_line=rec.line,
                )
            )

    def _emit_links(
        self,
        records: list[_Record],
        result: ParseResult,
        units: _UnitSystem,
        selected: set[str] | None,
    ) -> None:
        for rec in records:
            section = rec.section
            if section not in {"PIPES", "PUMPS", "VALVES"}:
                continue
            if not self._want(selected, section) or not rec.tokens:
                continue
            entity_id = rec.tokens[0]
            fields: dict[str, object] = {}
            self._link_endpoints(rec, result, entity_id, fields)
            if section == "PIPES":
                entity_type = "pipe"
                fields["length_m"] = self._norm(
                    result, rec, entity_id, "length_m", self._tok(rec, 3), "length", units
                )
                fields["diameter_mm"] = self._norm(
                    result, rec, entity_id, "diameter_mm", self._tok(rec, 4), "diameter", units
                )
                roughness = _to_float(self._tok(rec, 5))
                if roughness is not None:
                    fields["roughness"] = roughness
                minor = _to_float(self._tok(rec, 6))
                if minor is not None:
                    fields["minor_loss"] = minor
                if len(rec.tokens) > 7:
                    fields["status"] = rec.tokens[7]
            elif section == "PUMPS":
                entity_type = "pump"
                self._pump_params(rec, fields)
            else:
                entity_type = "valve"
                fields["diameter_mm"] = self._norm(
                    result, rec, entity_id, "diameter_mm", self._tok(rec, 3), "diameter", units
                )
                if len(rec.tokens) > 4:
                    fields["valve_type"] = rec.tokens[4].upper()
                setting = _to_float(self._tok(rec, 5))
                if setting is not None:
                    fields["setting"] = setting
                minor = _to_float(self._tok(rec, 6))
                if minor is not None:
                    fields["minor_loss"] = minor
            result.entities.append(
                ParsedEntity(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    name=entity_id,
                    fields={k: v for k, v in fields.items() if v is not None},
                    source_line=rec.line,
                )
            )

    def _link_endpoints(
        self, rec: _Record, result: ParseResult, entity_id: str, fields: dict[str, object]
    ) -> None:
        if len(rec.tokens) > 1:
            fields["node1"] = rec.tokens[1]
        else:
            result.unparsed.append(
                UnparsedItem(
                    line=rec.line,
                    section=rec.section,
                    entity_id=entity_id,
                    field="node1",
                    raw=rec.raw,
                    reason="link is missing its start node",
                )
            )
        if len(rec.tokens) > 2:
            fields["node2"] = rec.tokens[2]
        else:
            result.unparsed.append(
                UnparsedItem(
                    line=rec.line,
                    section=rec.section,
                    entity_id=entity_id,
                    field="node2",
                    raw=rec.raw,
                    reason="link is missing its end node",
                )
            )

    def _pump_params(self, rec: _Record, fields: dict[str, object]) -> None:
        tokens = rec.tokens[3:]
        idx = 0
        while idx < len(tokens) - 1:
            key = tokens[idx].upper()
            value = tokens[idx + 1]
            if key == "HEAD":
                fields["pump_curve"] = value
            elif key == "POWER":
                power = _to_float(value)
                if power is not None:
                    fields["power_kw"] = power
            elif key == "SPEED":
                speed = _to_float(value)
                if speed is not None:
                    fields["speed"] = speed
            elif key == "PATTERN":
                fields["speed_pattern"] = value
            idx += 2

    def _emit_curves(
        self, records: list[_Record], result: ParseResult, selected: set[str] | None
    ) -> None:
        if not self._want(selected, "CURVES"):
            return
        curves: dict[str, list[tuple[float, float]]] = {}
        first_line: dict[str, int] = {}
        for rec in records:
            if rec.section != "CURVES" or len(rec.tokens) < 3:
                continue
            x = _to_float(rec.tokens[1])
            y = _to_float(rec.tokens[2])
            if x is None or y is None:
                result.unparsed.append(
                    UnparsedItem(
                        line=rec.line,
                        section="CURVES",
                        entity_id=rec.tokens[0],
                        raw=rec.raw,
                        reason="non-numeric curve point",
                    )
                )
                continue
            curves.setdefault(rec.tokens[0], []).append((x, y))
            first_line.setdefault(rec.tokens[0], rec.line)
        for curve_id, points in curves.items():
            result.entities.append(
                ParsedEntity(
                    entity_type="curve",
                    entity_id=curve_id,
                    name=curve_id,
                    fields={"points": [list(p) for p in points], "point_count": len(points)},
                    source_line=first_line[curve_id],
                )
            )

    def _emit_patterns(
        self, records: list[_Record], result: ParseResult, selected: set[str] | None
    ) -> None:
        if not self._want(selected, "PATTERNS"):
            return
        patterns: dict[str, list[float]] = {}
        first_line: dict[str, int] = {}
        for rec in records:
            if rec.section != "PATTERNS" or len(rec.tokens) < 2:
                continue
            values = [_to_float(t) for t in rec.tokens[1:]]
            clean = [v for v in values if v is not None]
            if len(clean) != len(values):
                result.unparsed.append(
                    UnparsedItem(
                        line=rec.line,
                        section="PATTERNS",
                        entity_id=rec.tokens[0],
                        raw=rec.raw,
                        reason="non-numeric pattern multiplier",
                    )
                )
            patterns.setdefault(rec.tokens[0], []).extend(clean)
            first_line.setdefault(rec.tokens[0], rec.line)
        for pattern_id, multipliers in patterns.items():
            result.entities.append(
                ParsedEntity(
                    entity_type="pattern",
                    entity_id=pattern_id,
                    name=pattern_id,
                    fields={"multipliers": multipliers, "length": len(multipliers)},
                    source_line=first_line[pattern_id],
                )
            )

    @staticmethod
    def _tok(rec: _Record, idx: int) -> str:
        return rec.tokens[idx] if idx < len(rec.tokens) else ""
