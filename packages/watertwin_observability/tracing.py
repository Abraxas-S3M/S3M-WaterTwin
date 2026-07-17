"""OpenTelemetry trace wiring with graceful degradation.

Tracing is enabled by default but only *exports* spans when an OTLP endpoint is
configured (``OTEL_EXPORTER_OTLP_ENDPOINT``); otherwise spans are still created
(so ``trace_id``/``span_id`` appear in logs) but not shipped anywhere. Set
``WATERTWIN_TRACING_ENABLED=false`` (or ``OTEL_SDK_DISABLED=true``) to disable
tracing entirely, and ``WATERTWIN_TRACE_CONSOLE=true`` to also print spans to
stdout for local debugging.

All OpenTelemetry imports are optional: if the SDK is not installed the helpers
become no-ops so the services and their tests keep working.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("watertwin.observability.tracing")

_provider_configured = False


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def tracing_enabled() -> bool:
    """Return whether tracing should be configured for this process."""
    if _env_flag("OTEL_SDK_DISABLED", False):
        return False
    return _env_flag("WATERTWIN_TRACING_ENABLED", True)


def setup_tracing(service_name: str, app: object | None = None, version: str = "") -> object | None:
    """Configure a tracer provider and (optionally) instrument a FastAPI app.

    Returns the configured ``TracerProvider`` or ``None`` when tracing is
    disabled or the OpenTelemetry SDK is unavailable.
    """
    global _provider_configured

    if not tracing_enabled():
        logger.debug("tracing disabled for %s", service_name)
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )
    except Exception:  # pragma: no cover - otel SDK not installed
        logger.info("OpenTelemetry SDK not installed; tracing disabled for %s", service_name)
        return None

    provider = trace.get_tracer_provider()
    already_sdk_provider = isinstance(provider, TracerProvider)

    if not already_sdk_provider:
        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": version or "unknown",
            }
        )
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

    if not _provider_configured:
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
                logger.info("exporting traces via OTLP to %s", endpoint)
            except Exception:  # pragma: no cover - exporter extra not installed
                logger.warning("OTLP exporter unavailable; spans will not be exported")
        if _env_flag("WATERTWIN_TRACE_CONSOLE", False):
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        _provider_configured = True

    if app is not None:
        _instrument_fastapi(app)

    return provider


def _instrument_fastapi(app: object) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except Exception:  # pragma: no cover - instrumentation extra not installed
        logger.info("FastAPI instrumentation not installed; skipping auto request spans")
        return
    try:
        # Keep the metrics/health scrape endpoints out of the trace stream.
        excluded = os.environ.get("OTEL_PYTHON_FASTAPI_EXCLUDED_URLS", "metrics,health")
        FastAPIInstrumentor.instrument_app(app, excluded_urls=excluded)
    except Exception:  # pragma: no cover - already instrumented / incompatible
        logger.debug("FastAPI app already instrumented or instrumentation failed", exc_info=True)
