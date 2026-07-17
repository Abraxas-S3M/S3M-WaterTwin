# Observability

Every S3M-WaterTwin service is instrumented for the three observability pillars —
**metrics**, **traces** and **logs** — through a single shared package,
[`packages/watertwin_observability`](../../packages/watertwin_observability).
Everything here **observes only**; nothing in the observability path can write to
a control system (the advisory / read-only boundary is unchanged).

## What is instrumented

The three FastAPI services (`watertwin-api`, `hydraulic-sim`, `treatment-sim`)
each call `watertwin_observability.instrument_service(app, service_name, version)`
once at startup. That single call wires:

1. **Structured JSON logging** with correlation ids (stdout, one JSON object per
   line).
2. **Prometheus metrics** plus a `GET /metrics` endpoint.
3. **OpenTelemetry tracing** (auto request spans; graceful no-op when no SDK /
   exporter is configured).
4. Correlation-id middleware that ties all three together per request.

## Metrics

`GET /metrics` on each service exposes the Prometheus text exposition format.

| Metric | Type | Labels | Meaning |
| ------ | ---- | ------ | ------- |
| `http_requests_total` | counter | `service, method, path, status` | HTTP requests processed |
| `http_request_duration_seconds` | histogram | `service, method, path, status` | Request latency |
| `http_requests_in_progress` | gauge | `service, method` | In-flight requests |
| `watertwin_ingest_lag_seconds` | gauge | `service, source` | Age of the newest telemetry sample from the active read-only source (watertwin-api) |
| `watertwin_buffer_depth` | gauge | `service, buffer` | Queued/running simulation jobs (hydraulic-sim, treatment-sim) and pending recommendation cards (watertwin-api) |
| `watertwin_model_drift_ratio` | gauge | `service, model, metric` | Relative divergence between the treatment-sim RO model and the canonical analytical reference |
| `watertwin_audit_chain_length` | gauge | `service` | Events in the tamper-evident audit hash chain (watertwin-api) |
| `watertwin_service_info` | gauge | `service, version` | Static build metadata (always `1`) |

The `path` label is the matched **route template** (e.g. `/jobs/{job_id}`), not
the raw path, so label cardinality stays bounded. The domain gauges are refreshed
at scrape time via callbacks registered with `register_scrape_callback`, so the
values are always fresh and no background thread is needed.

## Traces

Tracing is enabled by default but only **exports** spans when an OTLP endpoint is
configured. Configure with standard OpenTelemetry environment variables:

| Variable | Effect |
| -------- | ------ |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP/HTTP collector URL; when set, spans are batch-exported there |
| `WATERTWIN_TRACING_ENABLED=false` | Disable tracing entirely (also honours `OTEL_SDK_DISABLED=true`) |
| `WATERTWIN_TRACE_CONSOLE=true` | Also print spans to stdout (local debugging) |

When no endpoint is configured, spans are still created (so `trace_id` /
`span_id` appear in logs) but not shipped anywhere. FastAPI requests are
auto-instrumented; the `/metrics` and `/health` scrape endpoints are excluded
from the trace stream.

## Logs

Logs are emitted as one JSON object per line to stdout. Every line carries:

```json
{
  "timestamp": "2026-01-01T00:00:00+00:00",
  "level": "INFO",
  "logger": "watertwin.store",
  "service": "watertwin-api",
  "message": "store connected to database",
  "correlation_id": "0f1e2d3c4b5a6978",
  "trace_id": "…",
  "span_id": "…"
}
```

`correlation_id` is present for anything logged while handling a request;
`trace_id` / `span_id` appear when a span is active. Any `extra={...}` fields
passed to the standard-library logger are merged in verbatim. Set `LOG_LEVEL` to
control verbosity.

## Correlation ids

For each HTTP request the middleware resolves a correlation id from the inbound
`X-Correlation-ID` (or `X-Request-ID`) header, minting a new one when absent. It
binds the id to the request context (so every log line carries it), stamps it
onto the active trace span, and echoes it back on the response as
`X-Correlation-ID`. This lets a single request be traced across logs, metrics
exemplars and spans, and across services.

## Running the stack

### docker-compose

`docker compose up --build` now also starts:

- **prometheus** (http://localhost:9090) — scrapes each service's `/metrics`
  (config: `infrastructure/prometheus/prometheus.yml`).
- **grafana** (http://localhost:3000, admin/admin) — datasource + the
  "WaterTwin — Service Observability" dashboard are auto-provisioned from
  `infrastructure/grafana/`.

### Kubernetes (Helm)

The `infrastructure/helm/watertwin-monitoring` chart deploys the same
Prometheus + Grafana stack (with the identical dashboard bundled):

```bash
helm install watertwin-monitoring infrastructure/helm/watertwin-monitoring
# customise scrape targets / persistence via values.yaml
```

## Tests

Each service has `tests/test_observability.py` asserting that `/metrics` exposes
the expected series and that log lines are valid JSON carrying a correlation id;
`packages/tests/test_observability.py` covers the shared toolkit (JSON formatter,
metric rendering, and correlation-id propagation through the middleware).
