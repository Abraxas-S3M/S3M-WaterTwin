# ADR-0014: Ingestion path threat model (hostile-input firewall)

- Status: Accepted
- Date: 2026-07-18
- Deciders: Security, Platform
- Related: `docs/security/threat-model.md` (platform STRIDE),
  `docs/security/control-boundaries.md`, `docs/security/iec62443-architecture.md`,
  ADR-0001 (advisory conductor, not physics), `services/watertwin-ingest/`

## Context

The `watertwin-ingest` service accepts **untrusted files** from customers (lab
exports, historian CSV drops, configuration bundles, S3M document packages). File
ingestion is the single largest hostile-input surface in a critical-
infrastructure product: a malicious or malformed upload is the classic path to
remote code execution, denial of service, data exfiltration and cross-tenant
compromise. WaterTwin is advisory and read-only to OT, so the ingest path must
never become a way to (a) reach the OT/control network, (b) exfiltrate another
tenant's data, or (c) take the platform down.

This ADR records the ingestion threat model. **Section 5** is the authoritative
threat table; each row is implemented by a control in `services/watertwin-ingest/`
and proven by an automated, blocking test under `security/tests/`. The row→
control→test mapping is maintained in `security/threat-model-ingestion.md`.

## Decision

1. Treat every uploaded file as hostile. Parse only behind a stack of controls
   (scan, archive limits, safe XML, safe CSV export, a resource-capped sandbox).
2. Isolate tenants strictly: a caller can only ever see its own tenant's data.
3. Deny-all egress from parser workers; allowlist only the S3M and watertwin-api
   endpoints. OT/MQTT/OPC UA are never reachable.
4. Make every action non-repudiable via a tamper-evident hash-chained audit log.
5. Keep the ingest service **optional and read-only to OT**: the platform is
   fully functional when it is stopped, and there is no control-write path.
6. Prove every threat-model row with a blocking test; block CI on the suite.

## Consequences

- A new, independently deployable, hardened service (`services/watertwin-ingest/`).
- A blocking CI job (`security-ingest`) runs the threat-model suite and a
  dependency (pip-audit) scan for the service.
- The service is added to SBOM generation and the open-source register.

## 1. Assets

- Uploaded file content and derived parsed artifacts (per tenant).
- Tenant isolation boundary (a tenant's data must never leak to another).
- Platform availability (a parse must not exhaust CPU/memory/disk).
- The tamper-evident audit trail (non-repudiation).
- The OT/control-network boundary (must remain unreachable from ingest).

## 2. Trust boundaries

- Untrusted uploader → ingest API (authenticated; tenant-scoped).
- Ingest API → parser worker (sandbox boundary; resource-capped, deny-all egress).
- Ingest service → platform (`watertwin-api`, S3M) — the only allowed egress.
- Ingest service ⇸ OT zone — **no** path exists (network + application enforced).

## 3. Actors

- Legitimate tenant users uploading data (authenticated).
- Malicious uploader (crafted files: malware, bombs, XXE, traversal, injection).
- Malicious/compromised tenant attempting cross-tenant access.
- Compromised parser (attempting exfiltration or OT reach).

## 4. Methodology

STRIDE, scoped to the ingestion path, prioritised by the file-parsing attack
surface and the critical-infrastructure safety invariants.

## 5. Threat model (authoritative)

| ID | STRIDE | Threat | Control | Test module |
|----|--------|--------|---------|-------------|
| T1 | Tampering | Malware-laden upload delivered for later execution / lateral spread | Signature-based malware scan (EICAR/AV), fail-closed; rejected before storage | `security/tests/test_t01_malware.py` |
| T2 | Denial of Service | Zip bomb (compression ratio, nesting depth, absolute size, member count) | Archive inspection + streamed extraction under hard caps | `security/tests/test_t02_zip_bomb.py` |
| T3 | Tampering / Information Disclosure | XXE, external entity, entity expansion ("billion laughs") in uploaded XML | defusedxml (DTD/entity/external forbidden) + byte pre-scan | `security/tests/test_t03_t04_xml.py` |
| T4 | Tampering | XSLT injection via `xml-stylesheet` processing instruction | Reject stylesheet PIs at pre-scan | `security/tests/test_t03_t04_xml.py` |
| T5 | Tampering | CSV/Formula injection executed on export in a spreadsheet | Escape leading `= + - @`/tab/CR on every exported cell | `security/tests/test_t05_csv_injection.py` |
| T6 | Tampering | Archive path traversal (Zip Slip) writing outside the extraction root | Reject absolute/`..` members; contained streamed extraction | `security/tests/test_t06_path_traversal.py` |
| T7 | Denial of Service | Parser resource exhaustion (CPU / memory) | Fresh-interpreter sandbox with wall-clock timeout + RLIMIT_AS/CPU caps | `security/tests/test_t07_parser_dos.py` |
| T8 | Elevation of Privilege / Tampering | Prompt injection in uploaded content coerces an action/approval | Content is inert data: no action, no approval change, no provenance change (markers only flag for a human) | `security/tests/test_t08_prompt_injection.py` |
| T9 | Tampering | Poisoned configuration with out-of-range values reaches analytics | Engineering validation against canonical models blocks out-of-range | `security/tests/test_t09_poisoned_config.py` |
| T10 | Information Disclosure | Cross-tenant read / list / content access | Strict tenant-scoped store; every read tenant-checked | `security/tests/test_t10_tenant_isolation.py` |
| T11 | Information Disclosure (Exfiltration) | Compromised parser exfiltrates data or reaches the OT network | Deny-all worker egress + allowlist; OT/MQTT/OPC UA always denied; k8s NetworkPolicy twin | `security/tests/test_t11_egress.py` |
| T12 | Repudiation | User denies uploading / approving content | Tamper-evident hash-chained audit from upload → approval, hash-verified | `security/tests/test_t12_repudiation.py` |

### Supporting controls (also tested + blocking)

| Area | Control | Test module |
|------|---------|-------------|
| Abuse / DoS | Per-tenant quotas: uploads/hour, total storage, concurrent parse jobs, per-file size — fail loudly | `security/tests/test_quotas.py` |
| Data lifecycle | Per-tenant retention; deletion removes content, audit entries survive | `security/tests/test_retention_residency.py` |
| Data sovereignty | Per-tenant data residency (Saudi critical-infrastructure default `SA`) | `security/tests/test_retention_residency.py` |
| Container | Non-root, read-only rootfs, dropped caps, seccomp, no shell | `security/tests/test_container_hardening.py` |
| Platform safety | Advisory/read-only invariant holds; OT-write-forbid guard covers ingest; ingest optional; one-way profile disables ingestion + hides nav | `security/tests/test_platform_invariants.py` |

## 6. Residual risk / accepted items

- Signature-based scanning catches known-bad content; a production deployment
  augments it with a maintained AV backend (ClamAV) behind the same fail-closed
  contract. The EICAR test proves the reject path, not full AV coverage.
- The sandbox is POSIX-only (relies on `resource` + process groups), matching the
  Linux runtime and CI. Non-POSIX hosts are out of scope for the runtime.
