"""Shared OT ingestion layer: read-only telemetry sources + tag normalization.

This package holds the platform's **read-only** OT connectors (synthetic /
OPC UA / Modbus / historian), the pluggable source resolver, and the
tag-normalization / tag-map schema. It is imported by every service that needs
to ingest telemetry -- both ``services/watertwin-api`` (existing behaviour, via
thin ``app.sources`` / ``app.tag_normalization`` compatibility shims) and the
independently deployable ``services/edge-gateway``.

The read-only posture is a build-breaking invariant: no module in
:mod:`ot_ingestion.sources` may contain a control-write path (OPC UA node write,
Modbus write function code, HTTP write verb, or SQL write statement). It is
enforced by the boundary-guard test that scans this package.
"""

from __future__ import annotations

__all__ = ["sources", "tag_normalization"]
