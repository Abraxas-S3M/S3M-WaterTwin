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
"""

from __future__ import annotations

__all__: list[str] = []
