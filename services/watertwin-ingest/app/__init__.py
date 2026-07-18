"""watertwin-ingest: staged-file data-intake service (advisory, read-only).

This service parses staged files a human uploaded (nameplates, pump curves,
datasheets), turns them into a reviewable diff of :class:`ProposedChange` rows,
and — in this phase — layers *optional* AI-assisted analysis (summary, anomaly
flags, drafted values) on top of that diff.

Hard boundary: this service analyzes; it never commits. It cannot write canonical
data, cannot approve, and cannot accept its own proposal. Every AI-derived field
is badged, carries a confidence score and a citation, and DEFAULTS TO UNACCEPTED.
Nothing here writes to any control system (SCADA / PLC / OPC UA / MQTT).
"""

from __future__ import annotations
