"""Structured JSON logging for S3M-WaterTwin.

Emitting one JSON object per log line keeps logs machine-parseable for auditing.
Every record carries the service name and the advisory ``control_mode`` so that
audit tooling can confirm, from the logs alone, that the platform ran in an
advisory-only posture.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from watertwin.safety import CONTROL_MODE

SERVICE_NAME = "s3m-watertwin"

# Attributes present on every ``logging.LogRecord``; anything not in this set is
# treated as caller-supplied structured context and merged into the JSON output.
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


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": SERVICE_NAME,
            "control_mode": CONTROL_MODE,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str, sort_keys=True)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger to emit structured JSON to stderr.

    Idempotent: repeated calls replace handlers rather than accumulating them.
    """

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Naming convention: ``s3m-watertwin.<name>``."""

    return logging.getLogger(f"{SERVICE_NAME}.{name}")
