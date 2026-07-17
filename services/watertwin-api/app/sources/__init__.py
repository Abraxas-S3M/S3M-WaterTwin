"""Read-only telemetry sources -- compatibility shim.

The read-only OT source adapters (synthetic / OPC UA / Modbus / historian) and
the pluggable source resolver were moved to the shared, importable
:mod:`ot_ingestion.sources` package so both this API and the independently
deployable ``services/edge-gateway`` reuse a single implementation (no
duplicated logic). This module re-exports that package unchanged so the existing
``app.sources`` import path (and its behaviour) is preserved.

Importing this shim also registers the API's existing synthetic plant
(``app.predictive_maintenance.ASSETS``) as the default synthetic asset provider,
so ``SyntheticSource()`` yields exactly the same telemetry as before the move.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ot_ingestion.sources import (  # noqa: F401
    SOURCE_KINDS,
    BUILTIN_SYNTHETIC_ASSETS,
    HistorianSource,
    ModbusSource,
    OpcUaSource,
    RegisterSpec,
    SourceResolution,
    SourceUnavailable,
    SyntheticAsset,
    SyntheticSource,
    TelemetrySource,
    parse_register_specs,
    register_default_assets_provider,
    resolve_source,
    unit_for,
)

# Import the synthetic shim for its import-time side effect: registering the
# API's synthetic plant as the default asset provider.
from . import synthetic as _synthetic  # noqa: F401

__all__ = [
    "SOURCE_KINDS",
    "BUILTIN_SYNTHETIC_ASSETS",
    "HistorianSource",
    "ModbusSource",
    "OpcUaSource",
    "RegisterSpec",
    "SourceResolution",
    "SourceUnavailable",
    "SyntheticAsset",
    "SyntheticSource",
    "TelemetrySource",
    "parse_register_specs",
    "register_default_assets_provider",
    "resolve_source",
    "unit_for",
]

logger = logging.getLogger("watertwin.sources")


# The API overrides the shared resolver with its own ``SourceResolution`` and a
# ``resolve_source`` that enforces the deployment directional guard (the one-way
# / data-diode profile, see app/deployment.py). The private source builders are
# not exported by ``ot_ingestion.sources``, so the guarded resolver keeps its
# own copy here.
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
