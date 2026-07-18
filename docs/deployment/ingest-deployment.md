# watertwin-ingest — deployment & container hardening

`watertwin-ingest` is the hardened, tenant-isolated, advisory file ingestion
service (the hostile-input firewall). This document covers how it is deployed and
the container-hardening controls it ships with. See also:

- Threat model: [`docs/adr/ADR-0014-ingestion-threat-model.md`](../adr/ADR-0014-ingestion-threat-model.md)
- Control→test map: [`security/threat-model-ingestion.md`](../../security/threat-model-ingestion.md)
- Network policy: [`ingest-network-policy.md`](./ingest-network-policy.md)
- Data residency: [`data-residency.md`](./data-residency.md)

## Posture

- **Advisory / read-only to OT.** No SCADA/PLC/OPC UA/MQTT path; no control write.
- **Optional.** The platform is fully functional when this service is stopped
  (nothing depends on it — asserted in CI).
- **Deny-all worker egress.** Only the S3M endpoint and the `watertwin-api`
  endpoint are reachable.

## Container hardening (shipped, and asserted by CI)

Every control below is enforced by `Dockerfile` + `deploy/deployment.yaml` and is
verified by `security/tests/test_container_hardening.py`, so a regression fails
the build.

| Control | How | Where |
|---------|-----|-------|
| **Non-root** | Runs as UID/GID `65532` (distroless `nonroot`); `runAsNonRoot: true` | `Dockerfile` (`USER 65532:65532`), `deploy/deployment.yaml` |
| **No shell in the runtime image** | Distroless base (`gcr.io/distroless/python3-debian12:nonroot`) — no shell, no package manager | `Dockerfile` (multi-stage; build tooling stays in the build stage) |
| **Read-only root filesystem** | `readOnlyRootFilesystem: true`; a memory-backed `emptyDir` tmpfs is mounted at `/tmp` for transient parse files only | `deploy/deployment.yaml` |
| **Dropped capabilities** | `capabilities.drop: [ALL]` | `deploy/deployment.yaml` |
| **No privilege escalation** | `allowPrivilegeEscalation: false` | `deploy/deployment.yaml` |
| **Seccomp** | `seccompProfile` (`Localhost` → `deploy/seccomp.json`, default-deny allowlist; `RuntimeDefault` acceptable fallback) | `deploy/deployment.yaml`, `deploy/seccomp.json` |
| **No service-account token** | `automountServiceAccountToken: false` | `deploy/deployment.yaml` |
| **Resource limits** | CPU/memory requests + limits bound blast radius | `deploy/deployment.yaml` |
| **In-process healthcheck** | `python -m app.healthcheck` (no shell, no socket) | `Dockerfile`, `app/healthcheck.py` |

### Build & run

```bash
# Build (from the repo root, so shared packages are in the build context):
docker build -f services/watertwin-ingest/Dockerfile -t watertwin-ingest:local .

# Apply the hardened k8s manifests:
kubectl apply -f services/watertwin-ingest/deploy/deployment.yaml
kubectl apply -f services/watertwin-ingest/deploy/networkpolicy.yaml
# Load the seccomp profile onto nodes at
#   /var/lib/kubelet/seccomp/watertwin/ingest-seccomp.json
```

Seccomp note: the profile is `defaultAction: SCMP_ACT_ERRNO` (deny) with an
explicit allowlist covering CPython, uvicorn, and the parse sandbox
(`fork`/`execve`, `setrlimit`, `setsid`, `kill`). If you cannot distribute a
custom profile, set `seccompProfile.type: RuntimeDefault` — still a meaningful
reduction of the kernel attack surface.

## Configuration (environment)

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEPLOYMENT_PROFILE` | `standard` | `standard` enables ingestion; `one_way_diode` disables it (and hides the dashboard nav item). Unknown → fails closed to `one_way_diode`. |
| `INGEST_MAX_UPLOADS_PER_HOUR` | `100` | Per-tenant upload rate cap. |
| `INGEST_MAX_STORAGE_BYTES_PER_TENANT` | `5 GiB` | Per-tenant total storage cap. |
| `INGEST_MAX_CONCURRENT_PARSE_JOBS` | `4` | Per-tenant concurrent parse cap. |
| `INGEST_MAX_UPLOAD_BYTES` | `100 MiB` | Per-file size cap. |
| `INGEST_MAX_ARCHIVE_UNCOMPRESSED_BYTES` | `512 MiB` | Zip-bomb absolute-size cap. |
| `INGEST_MAX_ARCHIVE_RATIO` | `120` | Zip-bomb compression-ratio cap. |
| `INGEST_MAX_ARCHIVE_DEPTH` | `3` | Archive nesting-depth cap. |
| `INGEST_MAX_ARCHIVE_MEMBERS` | `10000` | Archive member-count cap. |
| `INGEST_PARSE_TIMEOUT_SECONDS` | `30` | Parse-job wall-clock timeout. |
| `INGEST_PARSE_MEMORY_LIMIT_BYTES` | `512 MiB` | Parse-job memory cap. |
| `INGEST_DEFAULT_RETENTION_DAYS` | `90` | Default content-retention period. |
| `INGEST_DEFAULT_RESIDENCY_REGION` | `SA` | Default data-residency region. |
| `INGEST_S3M_ENDPOINT_URL` | `https://s3m.internal:443` | The only external egress target. |
| `INGEST_WATERTWIN_API_URL` | `http://watertwin-api:8000` | In-cluster advisory API egress target. |

All defaults are intentionally conservative (fail-safe) and are raised
deliberately per deployment.

## Stopping the service

Because nothing in the platform depends on `watertwin-ingest`, scaling it to zero
or deleting it leaves `watertwin-api`, the sims, and the dashboard fully
functional. The dashboard hides the ingestion nav item when the service reports
`ingestion_enabled: false` (or is unreachable).
