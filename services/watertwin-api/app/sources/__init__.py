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
