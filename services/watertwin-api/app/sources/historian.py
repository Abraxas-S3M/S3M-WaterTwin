"""Historian telemetry source -- compatibility shim.

Re-exports the shared :mod:`ot_ingestion.sources.historian` so the existing
``app.sources.historian`` import path is preserved after the move.
"""

from __future__ import annotations

from ot_ingestion.sources.historian import HistorianSource  # noqa: F401

__all__ = ["HistorianSource"]
