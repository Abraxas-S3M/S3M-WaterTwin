"""Structured JSON logging with correlation ids for the WaterTwin services.

Every service emits one JSON object per log line to stdout. Each line always
carries a ``timestamp`` (UTC, ISO-8601), ``level``, ``logger``, ``service`` and
``message``; the active ``correlation_id`` and the current OpenTelemetry
``trace_id`` / ``span_id`` are attached automatically when present, so logs,
metrics and traces can be correlated for a single request. Any structured
``extra=`` fields passed to the standard-library logger are merged in verbatim.

This module is deliberately free of third-party dependencies so it can be used
by every service (and its tests) without additional installs.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import sys
from typing import Any

from .context import get_correlation_id

# Standard :class:`logging.LogRecord` attributes that must not be treated as
# user-supplied structured ``extra`` fields when serialising a record.
_RESERVED_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

_MARKER = "_watertwin_json_handler"


def _trace_context() -> tuple[str | None, str | None]:
    """Return the current ``(trace_id, span_id)`` as hex, if a span is recording."""
    try:  # OpenTelemetry is optional; degrade gracefully when unavailable.
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx is None or not ctx.is_valid:
            return None, None
        return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
    except Exception:  # pragma: no cover - otel not installed / no active span
        return None, None


class JsonLogFormatter(logging.Formatter):
    """Format log records as single-line JSON objects with correlation context."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _dt.datetime.fromtimestamp(
                record.created, tz=_dt.UTC
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": self.service_name,
            "message": record.getMessage(),
        }

        correlation_id = get_correlation_id()
        if correlation_id:
            payload["correlation_id"] = correlation_id

        trace_id, span_id = _trace_context()
        if trace_id:
            payload["trace_id"] = trace_id
            payload["span_id"] = span_id

        # Merge structured extras (logger.info(..., extra={...})) verbatim, never
        # letting them clobber the canonical top-level fields.
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
                continue
            if key in payload:
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str)


def configure_logging(service_name: str, *, level: str | int | None = None) -> logging.Handler:
    """Install the JSON formatter on the root logger for ``service_name``.

    Idempotent: repeated calls replace the WaterTwin handler rather than stacking
    duplicates. Uvicorn's own loggers are re-pointed at the root handler so their
    access/error lines are emitted as JSON too. The level defaults to the
    ``LOG_LEVEL`` environment variable (falling back to ``INFO``).
    """
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())
    if not isinstance(level, int):
        level = logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    # Drop any handler we previously installed so re-configuration is clean.
    for existing in list(root.handlers):
        if getattr(existing, _MARKER, False):
            root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter(service_name))
    handler.setLevel(level)
    setattr(handler, _MARKER, True)
    root.addHandler(handler)

    # Route uvicorn/gunicorn loggers through the root handler as JSON.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True

    return handler
