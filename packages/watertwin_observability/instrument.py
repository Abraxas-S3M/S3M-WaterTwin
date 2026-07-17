"""One-call observability wiring for a WaterTwin FastAPI service.

:func:`instrument_service` installs structured JSON logging, the correlation-id
+ metrics middleware, a Prometheus ``/metrics`` endpoint and (optional)
OpenTelemetry tracing. Call it once at import time, right after the ``FastAPI``
app is created::

    from watertwin_observability import instrument_service

    app = FastAPI(...)
    instrument_service(app, service_name="watertwin-api", version="0.1.0")
"""

from __future__ import annotations

from typing import Any

from .logging_config import configure_logging
from .metrics import render_metrics, set_service_info
from .middleware import ObservabilityMiddleware
from .tracing import setup_tracing


def add_metrics_endpoint(app: Any, path: str = "/metrics") -> None:
    """Register a Prometheus text-exposition endpoint at ``path``."""
    from starlette.responses import Response

    async def metrics_endpoint(_request: Any) -> Response:
        body, content_type = render_metrics()
        return Response(content=body, media_type=content_type)

    app.add_route(path, metrics_endpoint, methods=["GET"], include_in_schema=False)


def instrument_service(
    app: Any,
    service_name: str,
    *,
    version: str = "",
    enable_tracing: bool = True,
    metrics_path: str = "/metrics",
) -> Any:
    """Wire logging, metrics, ``/metrics`` and tracing into ``app``.

    Middleware ordering matters: the observability middleware is added *before*
    tracing instrumentation so the OpenTelemetry request span (added last, hence
    outermost) is already active when the correlation id is stamped onto it.
    """
    configure_logging(service_name)
    set_service_info(service_name, version)

    app.add_middleware(ObservabilityMiddleware, service_name=service_name)
    add_metrics_endpoint(app, metrics_path)

    if enable_tracing:
        setup_tracing(service_name, app=app, version=version)

    return app
