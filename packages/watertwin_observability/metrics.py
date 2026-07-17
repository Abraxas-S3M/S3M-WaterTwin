"""Prometheus metric definitions shared by every WaterTwin service.

The registry is the process-global :data:`prometheus_client.REGISTRY`, so a
single ``/metrics`` scrape returns both the HTTP request metrics collected by
the observability middleware and the domain gauges (ingest lag, buffer depth,
model drift, audit-chain length) maintained by the individual services.

Domain gauges are refreshed at scrape time via lightweight callbacks registered
with :func:`register_scrape_callback`; this keeps the gauges fresh without a
background thread and avoids exposing stale values.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger("watertwin.observability.metrics")

# Latency buckets tuned for sub-second API calls up to slow simulation solves.
_LATENCY_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)

# -- HTTP request metrics (populated by the middleware) ---------------------

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests processed, labelled by service, method, route and status.",
    ("service", "method", "path", "status"),
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds, labelled by service, method, route and status.",
    ("service", "method", "path", "status"),
    buckets=_LATENCY_BUCKETS,
)

REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "In-flight HTTP requests, labelled by service and method.",
    ("service", "method"),
)

# -- Domain gauges (populated by each service at scrape time) ---------------

INGEST_LAG = Gauge(
    "watertwin_ingest_lag_seconds",
    "Age in seconds of the most recent telemetry sample ingested from a source.",
    ("service", "source"),
)

BUFFER_DEPTH = Gauge(
    "watertwin_buffer_depth",
    "Number of items currently buffered (e.g. queued/running simulation jobs).",
    ("service", "buffer"),
)

MODEL_DRIFT = Gauge(
    "watertwin_model_drift_ratio",
    "Relative drift between a model output and its reference (0 = in agreement).",
    ("service", "model", "metric"),
)

AUDIT_CHAIN_LENGTH = Gauge(
    "watertwin_audit_chain_length",
    "Number of events in the tamper-evident audit hash chain.",
    ("service",),
)

SERVICE_INFO = Gauge(
    "watertwin_service_info",
    "Static service metadata (always 1); labels carry service name and version.",
    ("service", "version"),
)


_scrape_callbacks: list[Callable[[], None]] = []


def register_scrape_callback(callback: Callable[[], None]) -> None:
    """Register ``callback`` to run (best-effort) on every ``/metrics`` scrape."""
    if callback not in _scrape_callbacks:
        _scrape_callbacks.append(callback)


def set_service_info(service_name: str, version: str = "") -> None:
    """Publish the static ``watertwin_service_info`` series for ``service_name``."""
    SERVICE_INFO.labels(service=service_name, version=version or "unknown").set(1)


def render_metrics() -> tuple[bytes, str]:
    """Run scrape callbacks and return ``(body, content_type)`` for ``/metrics``."""
    for callback in _scrape_callbacks:
        try:
            callback()
        except Exception:  # pragma: no cover - a bad callback must not break scrape
            logger.warning("metrics scrape callback failed", exc_info=True)
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
