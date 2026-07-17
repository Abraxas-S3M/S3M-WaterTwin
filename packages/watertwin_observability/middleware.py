"""Pure-ASGI middleware that ties correlation ids, metrics and traces together.

For every HTTP request it:

* resolves (or mints) a correlation id and binds it to the request context so
  every log line emitted while handling the request carries it;
* records request count / latency / in-flight Prometheus series labelled by the
  matched route template (bounding label cardinality);
* stamps the correlation id onto the active OpenTelemetry span (when tracing is
  enabled) and echoes it back on the response via ``X-Correlation-ID``.

Implemented as raw ASGI (rather than :class:`starlette.middleware.base`) so the
correlation-id :class:`~contextvars.ContextVar` set here is visible to the
downstream endpoint and its loggers.
"""

from __future__ import annotations

import time
from typing import Any

from .context import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from .metrics import REQUEST_COUNT, REQUEST_LATENCY, REQUESTS_IN_PROGRESS


def _header(scope: dict, name: str) -> str | None:
    target = name.lower().encode("latin-1")
    for key, value in scope.get("headers", []):
        if key == target:
            return value.decode("latin-1")
    return None


def _route_template(scope: dict) -> str:
    """Return the matched route path template, falling back to the raw path.

    Using the template (e.g. ``/jobs/{job_id}``) keeps metric label cardinality
    bounded regardless of how many distinct ids are requested.
    """
    route = scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path
    return scope.get("path", "unknown") or "unknown"


class ObservabilityMiddleware:
    """ASGI middleware providing correlation ids + HTTP request metrics."""

    def __init__(self, app: Any, service_name: str) -> None:
        self.app = app
        self.service_name = service_name

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = (
            _header(scope, CORRELATION_ID_HEADER)
            or _header(scope, REQUEST_ID_HEADER)
            or new_correlation_id()
        )
        token = set_correlation_id(correlation_id)

        self._annotate_span(correlation_id)

        method = scope.get("method", "GET")
        status_holder = {"code": 500}
        cid_bytes = correlation_id.encode("latin-1")
        header_name = CORRELATION_ID_HEADER.lower().encode("latin-1")

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = message.get("status", 200)
                headers = list(message.get("headers", []))
                headers = [h for h in headers if h[0] != header_name]
                headers.append((header_name, cid_bytes))
                message["headers"] = headers
            await send(message)

        in_progress = REQUESTS_IN_PROGRESS.labels(service=self.service_name, method=method)
        in_progress.inc()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            in_progress.dec()
            path = _route_template(scope)
            status = str(status_holder["code"])
            labels = {
                "service": self.service_name,
                "method": method,
                "path": path,
                "status": status,
            }
            REQUEST_LATENCY.labels(**labels).observe(duration)
            REQUEST_COUNT.labels(**labels).inc()
            reset_correlation_id(token)

    @staticmethod
    def _annotate_span(correlation_id: str) -> None:
        try:  # OpenTelemetry is optional.
            from opentelemetry import trace

            span = trace.get_current_span()
            if span is not None and span.is_recording():
                span.set_attribute("correlation_id", correlation_id)
        except Exception:  # pragma: no cover - otel not installed / no active span
            pass
