# Load, chaos & resilience tests

This directory holds the performance and resilience tests for the ingest + API
read paths.

## Load test (k6)

[`k6/ingest_read.js`](k6/ingest_read.js) drives the two hot paths:

- **ingest** — `POST /api/v1/ingestion/telemetry` (the edge store-and-forward
  destination), and
- **read** — `GET /health`, `/api/v1/ingestion/source`,
  `/api/v1/ingestion/telemetry/stats`, `/api/v1/audit/verify`,
  `/api/v1/recommendations`.

It has three profiles selected by `LOAD_PROFILE`:

| Profile | Shape | Purpose |
|---------|-------|---------|
| `smoke` (default) | 2 ingest + 3 read VUs for ~20s | CI-friendly breakage gate. |
| `load` | 10 ingest + 20 read VUs for 3m | Steady moderate load. |
| `soak` | 8 ingest + 12 read VUs for 30m | Longer run to surface drift/leaks. |

### Quick start

The smoke profile is self-contained — it boots a local in-memory API (auth
disabled) and runs k6 against it:

```bash
tests/load/run_smoke.sh
# or via make
make load-smoke
```

Against an already-running stack:

```bash
BASE_URL=http://localhost:8000 \
INGEST_TOKEN="$WATERTWIN_INGEST_TOKEN" \
AUTH_TOKEN="<bearer>" \
  LOAD_PROFILE=load k6 run tests/load/k6/ingest_read.js
```

`INGEST_TOKEN` is only needed when the API enforces the ingest token; `AUTH_TOKEN`
is only needed when the read endpoints are auth-gated. Both are optional (when the
API runs with auth disabled they can be omitted).

The smoke profile is wired into CI as a **non-blocking** job (`load-smoke`) so a
performance/breakage regression is surfaced without gating merges yet.

## Chaos test

[`../chaos/edge_gateway_chaos.sh`](../chaos/edge_gateway_chaos.sh) kills the
edge-gateway mid-stream and asserts store-and-forward recovers with no data loss
and a still-valid audit chain. It needs Docker and the compose stack. See the
script header and `docs/deployment/dr-runbook.md` for details.

## Disaster recovery drill

[`../../scripts/dr_drill.sh`](../../scripts/dr_drill.sh) exercises a `pg_dump`
backup + `pg_restore` and verifies audit-chain integrity post-restore. See
`docs/deployment/dr-runbook.md`.
