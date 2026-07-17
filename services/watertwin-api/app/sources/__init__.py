"""Pluggable, read-only telemetry sources.

The active source is selected by the ``OT_SOURCE`` environment variable
(``synthetic`` | ``opcua`` | ``modbus`` | ``historian``; default ``synthetic``).
When a real OT source is configured but unreachable/misconfigured, the resolver
logs and **falls back to the synthetic source** (it never crashes); the active
source and any fallback are surfaced in ``/health`` and
``GET /api/v1/ingestion/source``.

No source in this package writes to a control system. The read-only posture is
enforced by a boundary-guard test that scans this package for forbidden write
calls (mirroring the platform's control-write boundary guard).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .base import SourceUnavailable, TelemetrySource
from .historian import HistorianSource
from .modbus import ModbusSource, parse_register_specs
from .opcua import OpcUaSource
from .synthetic import SyntheticSource

logger = logging.getLogger("watertwin.sources")

#: All selectable source kinds.
SOURCE_KINDS = ("synthetic", "opcua", "modbus", "historian")

__all__ = [
    "SourceUnavailable",
    "TelemetrySource",
    "SyntheticSource",
    "OpcUaSource",
    "ModbusSource",
    "HistorianSource",
    "parse_register_specs",
    "SourceResolution",
    "resolve_source",
    "SOURCE_KINDS",
]


@dataclass
class SourceResolution:
    """The resolved active telemetry source + fallback state."""

    requested: str
    active: str
    source: TelemetrySource
    fallback: bool = False
    reason: Optional[str] = None

    def describe(self) -> dict:
        return {
            "requested_source": self.requested,
            "active_source": self.active,
            "fallback": self.fallback,
            "fallback_reason": self.reason,
            "available_sources": list(SOURCE_KINDS),
            "detail": self.source.describe(),
        }


def _load_tag_map(config):
    from ..tag_normalization import load_tag_map

    if not config.OT_TAG_MAP:
        raise SourceUnavailable(
            "OT_TAG_MAP is required for a real OT source (name under data/tag-maps/ or a path)"
        )
    try:
        return load_tag_map(config.OT_TAG_MAP)
    except Exception as exc:
        raise SourceUnavailable(f"could not load tag map {config.OT_TAG_MAP!r}: {exc}") from exc


def _build_opcua(config) -> TelemetrySource:
    if not config.OT_OPCUA_ENDPOINT:
        raise SourceUnavailable("OT_OPCUA_ENDPOINT is required for the opcua source")
    if not config.OT_OPCUA_NODE_IDS:
        raise SourceUnavailable("OT_OPCUA_NODE_IDS is required for the opcua source")
    return OpcUaSource(
        endpoint=config.OT_OPCUA_ENDPOINT,
        node_ids=config.OT_OPCUA_NODE_IDS,
        tag_map=_load_tag_map(config),
    )


def _build_modbus(config) -> TelemetrySource:
    if not config.OT_MODBUS_HOST:
        raise SourceUnavailable("OT_MODBUS_HOST is required for the modbus source")
    if not config.OT_MODBUS_REGISTERS:
        raise SourceUnavailable("OT_MODBUS_REGISTERS is required for the modbus source")
    try:
        registers = parse_register_specs(config.OT_MODBUS_REGISTERS)
    except ValueError as exc:
        raise SourceUnavailable(str(exc)) from exc
    return ModbusSource(
        host=config.OT_MODBUS_HOST,
        port=config.OT_MODBUS_PORT,
        unit=config.OT_MODBUS_UNIT,
        registers=registers,
        tag_map=_load_tag_map(config),
    )


def _build_historian(config) -> TelemetrySource:
    try:
        return HistorianSource(
            tag_map=_load_tag_map(config),
            access=config.OT_HISTORIAN_KIND,
            csv_path=config.OT_HISTORIAN_CSV_PATH,
            url=config.OT_HISTORIAN_URL,
            dsn=config.OT_HISTORIAN_DSN,
            query=config.OT_HISTORIAN_QUERY,
        )
    except ValueError as exc:
        raise SourceUnavailable(str(exc)) from exc


_BUILDERS = {
    "opcua": _build_opcua,
    "modbus": _build_modbus,
    "historian": _build_historian,
}


def resolve_source(config, *, probe: bool = True) -> SourceResolution:
    """Resolve the active telemetry source from config, with graceful fallback.

    Returns a :class:`SourceResolution`. If the requested real source cannot be
    built or probed, logs a warning and falls back to :class:`SyntheticSource`
    (the service never crashes because a real OT feed is down).
    """
    requested = (getattr(config, "OT_SOURCE", "synthetic") or "synthetic").strip().lower()

    if requested == "synthetic":
        return SourceResolution("synthetic", "synthetic", SyntheticSource())

    # Fail-closed directional guard: under the one-way / data-diode deployment
    # profile the platform must never initiate a connection toward the OT zone.
    # A platform->OT pull source is refused outright (it is NOT downgraded to a
    # silent synthetic fallback) so the misconfiguration is loud and the one-way
    # guarantee cannot be broken. See app/deployment.py.
    from .. import deployment

    deployment.assert_source_allowed(requested, config)

    builder = _BUILDERS.get(requested)
    if builder is None:
        reason = f"unknown OT_SOURCE {requested!r}; valid: {list(SOURCE_KINDS)}"
        logger.warning("%s -- falling back to synthetic source", reason)
        return SourceResolution(requested, "synthetic", SyntheticSource(), True, reason)

    try:
        source = builder(config)
        if probe:
            source.probe()
        logger.info("Active telemetry source: %s", source.name)
        return SourceResolution(requested, requested, source)
    except SourceUnavailable as exc:
        reason = str(exc)
    except Exception as exc:  # defensive: never crash on a real-source failure
        reason = f"{type(exc).__name__}: {exc}"

    logger.warning(
        "OT source %r unavailable (%s) -- falling back to synthetic source",
        requested,
        reason,
    )
    return SourceResolution(requested, "synthetic", SyntheticSource(), True, reason)
