"""Configuration for watertwin-ingest (environment-driven, safe defaults).

Every knob that affects the sandbox (wall-clock timeout, memory cap, scratch
directory, maximum upload size) is config-driven so an operator can tune the
worker envelope per deployment. Nothing here is ever a control-write path.
"""

from __future__ import annotations

import os
import tempfile

SERVICE_NAME = "watertwin-ingest"
SERVICE_VERSION = "0.1.0"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


#: Base URL of the watertwin-api service. The reconciler fetches the current
#: canonical configuration from here over HTTP (never from a database).
WATERTWIN_API_URL = os.environ.get("WATERTWIN_API_URL", "http://watertwin-api:8000")

#: Optional shared token presented to watertwin-api as ``X-Ingest-Token`` /
#: ``Authorization`` when fetching the canonical config. Read at request time.
WATERTWIN_API_TOKEN = os.environ.get("WATERTWIN_API_TOKEN") or None

#: Scratch directory the sandbox worker is allowed to write to. The container
#: root filesystem is mounted read-only; this is the *only* writable path.
SCRATCH_DIR = os.environ.get(
    "WATERTWIN_INGEST_SCRATCH_DIR",
    os.path.join(tempfile.gettempdir(), "watertwin-ingest"),
)

#: Wall-clock timeout (seconds) for a single parse job. A worker that exceeds
#: this is terminated and the job is marked ``parse_failed``.
PARSE_TIMEOUT_S = _env_float("WATERTWIN_INGEST_PARSE_TIMEOUT_S", 30.0)

#: Address-space (virtual memory) cap in MiB applied to the sandbox worker via
#: ``RLIMIT_AS``. A worker that exceeds it is killed and the job fails.
MEMORY_CAP_MB = _env_int("WATERTWIN_INGEST_MEMORY_MB", 512)

#: Maximum accepted upload size in bytes. Larger uploads are rejected before a
#: worker is ever spawned.
MAX_UPLOAD_BYTES = _env_int("WATERTWIN_INGEST_MAX_UPLOAD_BYTES", 20 * 1024 * 1024)

#: Maximum bytes the sandbox worker may write to its scratch dir (``RLIMIT_FSIZE``).
MAX_SCRATCH_BYTES = _env_int("WATERTWIN_INGEST_MAX_SCRATCH_BYTES", 64 * 1024 * 1024)

#: Fuzzy-name match confidence in [0, 1] below which a parsed entity is proposed
#: as NEW rather than matched to an existing canonical record.
MATCH_THRESHOLD = _env_float("WATERTWIN_INGEST_MATCH_THRESHOLD", 0.82)

#: Whether the sandbox worker is permitted to run as root. Default False: the
#: worker drops privileges when started as root and refuses to run otherwise.
ALLOW_ROOT_WORKER = _env_bool("WATERTWIN_INGEST_ALLOW_ROOT_WORKER", False)

#: CORS origins allowed to call this API (the dashboard).
CORS_ORIGINS = os.environ.get("WATERTWIN_INGEST_CORS_ORIGINS", "*").split(",")
