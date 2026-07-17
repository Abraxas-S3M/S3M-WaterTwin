"""Modbus telemetry source -- compatibility shim.

Re-exports the shared :mod:`ot_ingestion.sources.modbus` so the existing
``app.sources.modbus`` import path is preserved after the move.
"""

from __future__ import annotations

from ot_ingestion.sources.modbus import (  # noqa: F401
    ModbusSource,
    RegisterSpec,
    parse_register_specs,
)

__all__ = ["ModbusSource", "RegisterSpec", "parse_register_specs"]
