# edge-gateway

A read-only telemetry **store-and-forward** edge gateway for S3M-WaterTwin.

The gateway sits at the plant edge, reads/synthesizes telemetry, and forwards it
to the central `watertwin-api` ingest endpoint (`POST /api/v1/ingestion/telemetry`)
over a durable, on-disk spool. It is strictly read-only with respect to plant
control: it only reads telemetry and forwards it upstream — there is no
control-write path anywhere in this service.

## How store-and-forward works

1. **Producer** synthesizes a batch of canonical telemetry readings every
   `EDGE_BATCH_INTERVAL_S` and writes it atomically to the durable spool
   (`EDGE_SPOOL_DIR`, a mounted volume), tagged with a monotonically increasing,
   persisted sequence and a stable `batch_id` (`<gateway-id>-<seq>`).
2. **Forwarder** drains the spool oldest-first, POSTing each batch to the API and
   only deleting (`ack`-ing) it once upstream durably accepts it. While the API
   is unreachable, batches accumulate on disk and the forwarder retries with
   exponential backoff.

Because the spool is durable and the upstream ingest is **idempotent on
`batch_id`**, a gateway that is killed mid-stream loses nothing: on restart the
producer resumes numbering above the last batch and the forwarder replays every
un-acked batch, which upstream de-duplicates rather than double-counts. This is
exercised end-to-end by `tests/chaos/edge_gateway_chaos.sh`.

## Endpoints

| Method | Path      | Description |
|--------|-----------|-------------|
| GET    | `/health` | Liveness + live counters (produced/forwarded/spool depth). |
| GET    | `/stats`  | Same payload as `/health` (operational counters). |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `EDGE_GATEWAY_ID` | `edge-<hostname>` | Stable id; prefixes ingest batch ids. |
| `EDGE_API_URL` | `http://watertwin-api:8000` | Central API base URL. |
| `EDGE_INGEST_PATH` | `/api/v1/ingestion/telemetry` | Ingest path. |
| `EDGE_INGEST_TOKEN` | _(unset)_ | `X-Ingest-Token` presented to the API (needed when the API enforces auth). |
| `EDGE_SPOOL_DIR` | `/data/spool` | Durable spool directory (mount a volume). |
| `EDGE_BATCH_INTERVAL_S` | `1.0` | Seconds between produced batches. |
| `EDGE_FORWARD_INTERVAL_S` | `0.5` | Forwarder poll interval. |
| `EDGE_FORWARD_MAX_BACKOFF_S` | `10.0` | Max backoff between failed forwards. |
| `EDGE_FORWARD_TIMEOUT_S` | `5.0` | HTTP timeout per forward attempt. |
| `EDGE_MAX_BATCHES` | `0` | Stop producing after N batches (0 = forever). |
| `EDGE_PRODUCE_ENABLED` | `true` | Enable the producer loop. |

## Tests

```bash
cd services/edge-gateway && python -m pytest -q
```
