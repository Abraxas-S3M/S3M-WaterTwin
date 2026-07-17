# edge-gateway

An **outbound-only, read-only OT edge collector**. It runs at the plant edge
(behind the OT firewall), reads real OT feeds strictly read-only, validates and
normalizes them, buffers everything locally in an **encrypted store-and-forward**
queue, and **pushes** canonical telemetry outbound to the `watertwin-api` ingest
endpoint. It never opens an inbound listener and has no inbound internet
dependency.

## What it does

1. **Read-only collection.** Reuses the shared `ot_ingestion.sources` adapters
   (OPC UA client / Modbus read function codes / historian pull / synthetic) —
   the *same* code the API uses, moved to `packages/ot_ingestion` so there is no
   duplicated logic. The active source is chosen by `OT_SOURCE`; if a configured
   real source is unreachable the resolver **falls back to synthetic** (never
   crashes).
2. **Data-quality validation.** Each reading is scored for range / staleness /
   frozen-signal / deadband and tagged with a quality flag
   (`good` / `out_of_range` / `stale` / `frozen` / `deadband` / `non_finite`).
3. **Time-sync + monotonic timestamping, unit conversion, tag normalization.**
   Readings get a monotonically non-decreasing gateway timestamp (with reported
   source-clock skew), are converted to canonical units, and are normalized onto
   the canonical model via the shared tag-map schema.
4. **Encrypted store-and-forward buffer.** Everything is appended to a local
   SQLite queue whose payloads are encrypted at rest (Fernet: AES-128-CBC +
   HMAC-SHA256). The buffer survives restarts and network outages; rows are
   acked (deleted) only once the API confirms receipt.
5. **Outbound-only push.** The only network path is an outbound HTTP client to
   `POST {EDGE_GATEWAY_API_URL}{EDGE_GATEWAY_INGEST_PATH}`.
6. **Source-health reporting.** A health snapshot (active/fallback source,
   read/forward failures, buffer depth, clock skew) rides along with every push
   and appears on the API's `/api/v1/ingestion/telemetry/latest` view.

## Read-only / outbound-only invariants

- No module in the shared `ot_ingestion.sources` package contains a
  control-write path — enforced by the boundary-guard test
  (`services/watertwin-api/tests/test_ot_sources.py::test_sources_package_has_no_write_path`),
  which scans the moved shared package.
- The gateway binds **no** inbound socket — enforced by
  `tests/test_outbound_only.py` (a static scan for server constructs plus a
  runtime assertion that a full collect+forward cycle never calls
  `socket.bind` / `socket.listen`).

## Running

```bash
# As part of the stack:
docker compose up --build edge-gateway

# Locally (worker loop, no server):
PYTHONPATH=../../packages python -m app.main
```

## Configuration (environment)

| Variable | Default | Purpose |
|----------|---------|---------|
| `OT_SOURCE` | `synthetic` | `synthetic` / `opcua` / `modbus` / `historian` |
| `OT_TAG_MAP` | – | tag map name (under `data/tag-maps/`) or path (real sources) |
| `EDGE_GATEWAY_API_URL` | `http://watertwin-api:8000` | outbound push target base URL |
| `EDGE_GATEWAY_INGEST_PATH` | `/api/v1/ingestion/telemetry` | ingest path |
| `EDGE_GATEWAY_API_TOKEN` | – | optional bearer token presented to the API |
| `EDGE_GATEWAY_BUFFER_PATH` | `/data/edge-buffer.db` | encrypted buffer file |
| `EDGE_GATEWAY_BUFFER_KEY` | – | passphrase for the at-rest encryption key (**set + keep stable**) |
| `EDGE_GATEWAY_FORWARD_BATCH_SIZE` | `500` | rows pushed per forward attempt |
| `EDGE_GATEWAY_BUFFER_MAX_ROWS` | `500000` | buffer cap (oldest dropped past this) |
| `EDGE_GATEWAY_POLL_INTERVAL_S` | `5` | seconds between polls |
| `EDGE_GATEWAY_STALENESS_LIMIT_S` | `60` | age past which a reading is `stale` |
| `EDGE_GATEWAY_FROZEN_LIMIT` | `10` | identical samples before `frozen` |
| `EDGE_GATEWAY_DEADBAND` | `0.0` | change below which a reading is `deadband` |

The same `OT_*` OPC UA / Modbus / historian variables as `watertwin-api` are
honored (the source resolver is shared).
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
python -m pytest -q
```

Covers buffer persistence across restart, store-and-forward replay after an
outage, data-quality flagging, and the outbound-only (no inbound bind) posture.
cd services/edge-gateway && python -m pytest -q
```
