"""Runtime configuration sourced from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    tick_seconds: float = 5.0
    s3m_base_url: str = ""
    s3m_timeout: float = 2.0
    seed: int = 42
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            tick_seconds=_get_float("WATERTWIN_TICK_SECONDS", 5.0),
            s3m_base_url=os.environ.get("WATERTWIN_S3M_BASE_URL", ""),
            s3m_timeout=_get_float("WATERTWIN_S3M_TIMEOUT", 2.0),
            seed=_get_int("WATERTWIN_SEED", 42),
            log_level=os.environ.get("WATERTWIN_LOG_LEVEL", "INFO"),
        )
