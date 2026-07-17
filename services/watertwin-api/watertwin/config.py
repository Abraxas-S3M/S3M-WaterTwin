"""Runtime configuration and structured logging for the WaterTwin service.

Settings are sourced from environment variables (all prefixed ``WATERTWIN_`` where
noted, plus a few well-known unprefixed names for interop with the wider S3M stack).
Nothing here requires Postgres or S3M-Core to be reachable; every dependency is
optional and degrades gracefully at the layer that uses it.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings for the WaterTwin API service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Optional durable store; when unset the store runs purely in memory.
    database_url: str | None = Field(default=None, alias="WATERTWIN_DATABASE_URL")

    # S3M-Core quad-engine endpoint; local fallback is used if unreachable.
    s3m_core_url: str = Field(default="http://localhost:8081", alias="S3M_CORE_URL")

    # Simulation / polling cadence in seconds.
    tick_seconds: int = Field(default=4, alias="TICK_SECONDS")

    facility_id: str = Field(default="facility-unknown", alias="FACILITY_ID")
    train_id: str = Field(default="train-unknown", alias="TRAIN_ID")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()


class JsonLogFormatter(logging.Formatter):
    """Formatter emitting one structured JSON object per log record."""

    _RESERVED = frozenset(
        {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "module", "msecs",
            "message", "msg", "name", "pathname", "process", "processName",
            "relativeCreated", "stack_info", "thread", "threadName", "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        # Merge any structured extras attached to the record.
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str, sort_keys=True)


def configure_logging(level: str | None = None) -> None:
    """Configure root logging to emit structured JSON to stdout.

    Idempotent: repeated calls replace the handler rather than stacking them.
    """
    resolved = (level or get_settings().log_level or "INFO").upper()
    root = logging.getLogger()
    root.setLevel(resolved)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonLogFormatter())

    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
