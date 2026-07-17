"""Telemetry source abstraction -- compatibility shim.

Re-exports the shared :mod:`ot_ingestion.sources.base` so the existing
``app.sources.base`` import path is preserved after the move.
"""

from __future__ import annotations

from ot_ingestion.sources.base import SourceUnavailable, TelemetrySource  # noqa: F401

__all__ = ["SourceUnavailable", "TelemetrySource"]
