"""edge-gateway: an outbound-only, read-only OT edge collector.

The edge-gateway runs at the plant edge (behind the OT firewall). It:

* reads real OT feeds strictly read-only, reusing the shared
  :mod:`ot_ingestion.sources` adapters (OPC UA / Modbus / historian) with
  graceful fallback to synthetic when the real source is down;
* validates data quality (range / staleness / frozen-signal / deadband) and
  attaches quality flags;
* time-synchronizes + monotonically timestamps, converts units, and normalizes
  customer tags onto the canonical model (reusing the shared tag-map schema);
* buffers everything in a local **encrypted** SQLite store-and-forward queue so
  nothing is lost across restarts or network outages; and
* PUSHES canonical readings OUTBOUND to the watertwin-api ingest endpoint.

It never binds an inbound listener and has no inbound internet dependency.
"""

from __future__ import annotations

__all__: list[str] = []
"""S3M-WaterTwin edge-gateway: read-only telemetry store-and-forward."""
