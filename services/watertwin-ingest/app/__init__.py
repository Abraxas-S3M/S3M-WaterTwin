"""watertwin-ingest: hardened, tenant-isolated file/document ingestion service.

The ingest service accepts customer file uploads (lab exports, historian CSV
drops, configuration bundles, S3M document packages) and turns them into
canonical, validated content for the advisory platform. Its entire reason to
exist is to be the *hostile-input firewall* in front of the rest of WaterTwin:
every file that arrives is untrusted, so every parser runs behind a stack of
security controls (malware scan, archive/zip-bomb limits, XXE/XSLT-safe XML,
CSV-injection-safe export, a resource-capped sandbox, per-tenant quotas, strict
tenant isolation, and a tamper-evident audit chain).

Safety posture (identical to the rest of the platform, never weakened here):

* ``control_mode = "advisory"`` — the service produces advisory content only.
* ``operator_approval_required = True`` — nothing derived from an upload is
  acted upon without human approval.
* ``control_write_enabled = False`` — there is **no** control-write path in this
  service. It never talks to SCADA / PLC / OPC UA / MQTT (enforced by the
  OT-write-forbid guard and the deny-all egress policy).
* The LLM/assistant has no database access here and issues no control command;
  uploaded content is treated as inert data, never as instructions.

Every control is mapped to a threat-model row and an automated test in
``security/threat-model-ingestion.md`` and ``security/tests/``.
"""watertwin-ingest: sandboxed customer-file ingestion for the water twin.

This service accepts a customer-supplied engineering file (Phase C: EPANET 2.2
``.inp`` network models), parses it inside a hardened sandbox worker, reconciles
the parsed entities against the *current canonical configuration* (fetched from
``watertwin-api`` over HTTP — never a direct database read), and produces a
field-level :class:`~app.proposal.ChangeProposal` for human review.

Safety posture (unchanged by this service):

* It is strictly **read-only** with respect to the canonical model and to OT.
  Nothing here writes to the canonical config, and there is no SCADA/PLC/OPC UA/
  MQTT code path anywhere in the service.
* Parsing is *advisory*: a :class:`ChangeProposal` is a proposal, never an applied
  change. Every :class:`~app.proposal.ProposedChange` defaults ``accepted=False``
  and there is no server-side code path that flips it True.
* Classification of an uploaded file must be **confirmed by a human** before the
  file is parsed — a critical-infrastructure file is never processed on a guess.
"""watertwin-ingest: bulk file-import staging service.

This service ingests two large-file classes that do not arrive over the live OT
telemetry path:

* **historian time-series exports** (``.csv`` / ``.parquet``, up to ~500 MB), and
* **customer geospatial layers** (``.geojson`` / zipped shapefile).

Every parser here is **read-only with respect to the plant**: it reads a file the
customer supplied, resolves it against configuration, writes the result to a
*staging* area, and emits an **approval proposal**. Nothing is streamed straight
into the analytic store, no control system is ever written, and importing a file
never promotes an analytic from ``preliminary`` to ``calibrated`` -- only the
documented, engineer-signed validation process does that.
"""watertwin-ingest: immutable customer-file intake service.

Optional, independently deployable. Receives customer files, stores them
immutably (content-addressed, write-once), scans them structurally, and tracks
them through a status lifecycle. No parsing. No direct database access. No OT
network access.
"""
"""watertwin-ingest: templated spreadsheet ingestion for the workbench.

Read-only, decision-support ingestion of the three highest-volume hand-entry
burdens -- equipment specifications, OT tag mappings and lab methods -- from
customer-filled CSV/XLSX templates into a reviewable diff. This service parses
uploaded files only; it never connects to, or writes to, any OT/SCADA/PLC/OPC
UA/MQTT system, and it issues no control commands.
"""

from __future__ import annotations

__all__: list[str] = []
__all__ = ["__version__"]

__version__ = "0.1.0"
