# Ingestion Threat Model — Controls & Proof (ADR-0014)

This document maps **every row of ADR-0014 section 5** (the ingestion threat
model) to the concrete control that implements it and the automated, **blocking**
test that proves it. An external reviewer should be able to read this table and,
for each control, open the named source file and test file without asking a
question.

- Threat model of record: [`docs/adr/ADR-0014-ingestion-threat-model.md`](../docs/adr/ADR-0014-ingestion-threat-model.md)
- Service under test: [`services/watertwin-ingest/`](../services/watertwin-ingest/)
- Test suite (blocking in CI job `security-ingest`): [`security/tests/`](./tests/)

Run the suite locally:

```bash
python -m pytest security/tests -q
```

## Safety invariants (non-negotiable, verified by the suite)

The ingest service never weakens the platform invariants, and the suite asserts
each one:

- `control_mode = "advisory"`, `operator_approval_required = true`,
  `control_write_enabled = false` everywhere
  (`test_platform_invariants.py::test_safety_invariant_intact`).
- No code path writes to SCADA / PLC / OPC UA / MQTT — the OT-write-forbid guard
  scans the whole service
  (`test_platform_invariants.py::test_ot_write_forbid_guard_covers_ingest_service`).
- The LLM/assistant gets no database access and issues no control command here;
  uploaded content is inert data
  (`test_t08_prompt_injection.py`).

## Threat-model row → control → test

| ID | Threat (ADR-0014 §5) | Control (implementation) | Proving test |
|----|----------------------|--------------------------|--------------|
| **T1** | Malware-laden upload | Signature/AV scan, fail-closed, before storage — `app/scanning.py`; wired in `app/service.py` | `tests/test_t01_malware.py` — EICAR rejected end-to-end |
| **T2** | Zip bomb (ratio / depth / absolute size / members) | Archive caps + streamed extraction — `app/archives.py` (`ArchiveLimits`, `inspect_zip`, `safe_extract`) | `tests/test_t02_zip_bomb.py` — ratio, absolute size, member count, nesting depth |
| **T3** | XXE / external entity / entity expansion | defusedxml + byte pre-scan — `app/xml_safe.py` | `tests/test_t03_t04_xml.py` — XXE, external DTD, billion-laughs blocked |
| **T4** | XSLT injection (`xml-stylesheet` PI) | Reject stylesheet PIs — `app/xml_safe.py` | `tests/test_t03_t04_xml.py::test_xslt_stylesheet_pi_blocked` |
| **T5** | CSV / formula injection on export | Escape `= + - @`/tab/CR — `app/csv_safe.py` | `tests/test_t05_csv_injection.py` — dangerous cells escaped, benign untouched |
| **T6** | Archive path traversal (Zip Slip) | Reject absolute/`..` members; contained extraction — `app/archives.py` (`_safe_member_path`) | `tests/test_t06_path_traversal.py` — relative + absolute traversal rejected, nothing escapes root |
| **T7** | Parser DoS (CPU / memory) | Fresh-interpreter sandbox: wall-clock timeout + `RLIMIT_AS`/`RLIMIT_CPU` — `app/limits.py`, `app/sandbox_runner.py` | `tests/test_t07_parser_dos.py` — timeout enforced, memory cap enforced, parent survives |
| **T8** | Prompt injection in content | Inert data: no action, approval/provenance immutable — `app/provenance.py`, `app/service.py` | `tests/test_t08_prompt_injection.py` — flagged only; no approval, no provenance change, boundary unchanged |
| **T9** | Poisoned configuration (out-of-range) | Engineering validation vs. canonical models — `app/engineering_validation.py` | `tests/test_t09_poisoned_config.py` — out-of-range membrane recovery/efficiency/alarm order rejected |
| **T10** | Cross-tenant read / list / content | Tenant-scoped store; every read tenant-checked — `app/tenancy.py`, `app/service.py` | `tests/test_t10_tenant_isolation.py` — cross-tenant read, list, content, delete all denied |
| **T11** | Exfiltration / worker egress; OT reach | Deny-all egress + allowlist; OT/MQTT/OPC UA always denied — `app/egress.py`; k8s twin `deploy/networkpolicy.yaml` | `tests/test_t11_egress.py` — arbitrary egress denied, OT ports/hosts unreachable, manifest has no OT egress |
| **T12** | Repudiation | Hash-chained audit upload→approval — `app/audit.py`, `app/service.py` | `tests/test_t12_repudiation.py` — full chain, hash-verified, tampering/deletion detected |

## Supporting controls (also blocking)

| Area | Control | Proving test |
|------|---------|--------------|
| Rate limits & quotas | Per-tenant uploads/hour, total storage, concurrent parse jobs, per-file size — fail loudly (`app/quotas.py`) | `tests/test_quotas.py` |
| Retention | Per-tenant retention; deletion removes **content**, **audit entries survive** (`app/retention.py`, `app/service.py`) | `tests/test_retention_residency.py` |
| Data residency | Per-tenant storage region; Saudi critical-infrastructure default `SA` (`app/residency.py`) | `tests/test_retention_residency.py` |
| Container hardening | Non-root, read-only rootfs, dropped caps, seccomp, no shell (`Dockerfile`, `deploy/`) | `tests/test_container_hardening.py` |
| Platform independence | Ingest is optional; stopping it leaves the platform fully functional (no reverse deps) | `tests/test_platform_invariants.py::test_no_other_component_imports_the_ingest_service` |
| One-way deployment | `DEPLOYMENT_PROFILE=one_way_diode` disables ingestion and hides the nav item (`app/deployment.py`) | `tests/test_platform_invariants.py::test_one_way_diode_disables_ingestion_and_hides_nav` |

## What survives deletion (and what does not)

See [`docs/deployment/data-residency.md`](../docs/deployment/data-residency.md):

- **Survives:** the tamper-evident audit entries (upload received / scanned /
  parsed / approved / deleted) and their hashes. These contain metadata only —
  never file content.
- **Does not survive:** the uploaded file content and derived parsed artifacts.
  On deletion (explicit or retention-driven) the bytes are removed and the
  tenant's storage quota is returned; only a `deleted` audit event remains.

## Deliberately left undone

- Production AV integration (ClamAV/clamd) is stubbed behind the same
  fail-closed `ScanResult` contract; the EICAR test proves the reject path but
  not full malware coverage. See ADR-0014 §6.
- The parser sandbox is POSIX-only by design (Linux runtime + CI).
