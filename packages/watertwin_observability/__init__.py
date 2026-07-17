"""Shared observability toolkit for the S3M-WaterTwin services.

Provides a single, dependency-light place for the three FastAPI services
(``watertwin-api``, ``hydraulic-sim``, ``treatment-sim``) to obtain:

* **Structured JSON logging** with correlation ids and trace context
  (:mod:`watertwin_observability.logging_config`).
* **Prometheus metrics** — HTTP latency/throughput plus the domain gauges
  ingest lag, buffer depth, model drift and audit-chain length
  (:mod:`watertwin_observability.metrics`).
* **OpenTelemetry tracing** with graceful degradation
  (:mod:`watertwin_observability.tracing`).
* A one-call :func:`instrument_service` that wires all of the above (plus a
  ``/metrics`` endpoint) into a FastAPI app.

Nothing in this package touches a control system; it only observes.
"""

from __future__ import annotations

from .context import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    get_correlation_id,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from .instrument import add_metrics_endpoint, instrument_service
from .logging_config import JsonLogFormatter, configure_logging
from .metrics import (
    AUDIT_CHAIN_LENGTH,
    BUFFER_DEPTH,
    INGEST_LAG,
    MODEL_DRIFT,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    register_scrape_callback,
    render_metrics,
    set_service_info,
)
from .middleware import ObservabilityMiddleware
from .tracing import setup_tracing, tracing_enabled

__all__ = [
    "AUDIT_CHAIN_LENGTH",
    "BUFFER_DEPTH",
    "CORRELATION_ID_HEADER",
    "INGEST_LAG",
    "MODEL_DRIFT",
    "REQUEST_COUNT",
    "REQUEST_ID_HEADER",
    "REQUEST_LATENCY",
    "JsonLogFormatter",
    "ObservabilityMiddleware",
    "add_metrics_endpoint",
    "configure_logging",
    "get_correlation_id",
    "instrument_service",
    "new_correlation_id",
    "register_scrape_callback",
    "render_metrics",
    "reset_correlation_id",
    "set_correlation_id",
    "set_service_info",
    "setup_tracing",
    "tracing_enabled",
]
