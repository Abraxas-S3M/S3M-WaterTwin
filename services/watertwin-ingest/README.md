# watertwin-ingest

A **hardened, tenant-isolated, advisory** file/document ingestion service. It is
the *hostile-input firewall* in front of the rest of S3M-WaterTwin: every
uploaded file is untrusted, so every parser runs behind a stack of security
controls. The service is **read-only to OT** (no SCADA/PLC/OPC UA/MQTT path) and
has **no control-write path** anywhere.

## Safety posture (never weakened here)

- `control_mode = "advisory"`, `operator_approval_required = true`,
  `control_write_enabled = false` — stamped on every response and audit entry.
- Parser workers have **deny-all egress**; OT/MQTT/OPC UA are always denied.
- Uploaded content is inert **data**, never instructions: ingestion takes no
  action, changes no approval, and never mutates provenance (prompt-injection
  safe).

## Controls (each mapped to a threat-model row + test)

| Control | Module | Threat-model row |
|---------|--------|------------------|
| Malware scan (EICAR/AV, fail-closed) | `app/scanning.py` | T1 |
| Zip-bomb limits (ratio / depth / size / members) | `app/archives.py` | T2 |
| XXE / external-entity / entity-expansion safe XML | `app/xml_safe.py` | T3 |
| XSLT stylesheet-PI rejection | `app/xml_safe.py` | T4 |
| CSV formula-injection escaping on export | `app/csv_safe.py` | T5 |
| Archive path-traversal (Zip Slip) prevention | `app/archives.py` | T6 |
| Parser DoS sandbox (timeout + memory cap) | `app/limits.py` | T7 |
| Prompt-injection inertness | `app/provenance.py` | T8 |
| Poisoned-config engineering validation | `app/engineering_validation.py` | T9 |
| Cross-tenant isolation (read/list/content) | `app/tenancy.py` | T10 |
| Deny-all worker egress / no OT reachability | `app/egress.py` | T11 |
| Tamper-evident hash-chained audit | `app/audit.py` | T12 |
| Per-tenant quotas (uploads/storage/concurrency) | `app/quotas.py` | quotas |
| Per-tenant retention + deletion behaviour | `app/retention.py` | retention |
| Per-tenant data residency (Saudi CI) | `app/residency.py` | residency |
| One-way-diode gate (ingestion off, nav hidden) | `app/deployment.py` | invariant |

The authoritative threat model and control→test mapping is
[`security/threat-model-ingestion.md`](../../security/threat-model-ingestion.md);
the blocking test suite is under [`security/tests/`](../../security/tests/).

## Container hardening

See `Dockerfile` and `deploy/`:

- distroless runtime image — **no shell**, non-root (UID 65532)
- `readOnlyRootFilesystem`, all capabilities dropped, `allowPrivilegeEscalation:
  false`, seccomp profile (`deploy/seccomp.json`)
- deny-all egress `NetworkPolicy` (`deploy/networkpolicy.yaml`)

## Running

```bash
# Locally (dev):
PYTHONPATH=../../packages:. python -m uvicorn app.main:app --port 8300

# Tests:
python -m pytest -q          # service smoke tests
# (the exhaustive threat-model suite lives in ../../security/tests)
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness + fixed advisory/read-only posture. |
| GET | `/capabilities` | Dashboard nav gating + safety posture. |
| POST | `/api/v1/ingest/uploads?parser=&filename=` | Upload raw file body; runs the full control pipeline. |
| GET | `/api/v1/ingest/uploads` | List the caller-tenant's uploads. |
| GET | `/api/v1/ingest/uploads/{id}` | Upload metadata (tenant-checked). |
| GET | `/api/v1/ingest/uploads/{id}/content` | Upload content (tenant-checked). |
| GET | `/api/v1/ingest/uploads/{id}/audit` | Hash-chained audit trail for the upload. |

The tenant is taken from the `X-Tenant-Id` header (a stand-in for the Keycloak
JWT tenant claim; wired to real identity in deployment).

## Platform independence

This service is **optional**: the platform is fully functional when it is
stopped. Nothing in `packages/` or the other services imports it (asserted by
`security/tests/test_platform_invariants.py`).
