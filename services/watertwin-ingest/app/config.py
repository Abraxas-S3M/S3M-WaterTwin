"""Configuration for watertwin-ingest (all env-driven).

The ingest service is an OPTIONAL, independently deployable intake surface. It
receives customer files, stores them immutably (content-addressed, write-once),
scans them structurally, and tracks them through a status lifecycle. It has:

* **No direct database connection** to the canonical store. It talks to
  watertwin-api over the same authenticated HTTP API a human uses (see
  :mod:`app.audit_client`).
* **No OT network access.** It cannot reach MQTT, OPC UA, Modbus, or the edge
  gateway. The OT-write-forbid guard is extended to cover this service (see
  ``tests/test_ot_write_forbid.py``).

Deployment-profile awareness mirrors watertwin-api's ``DEPLOYMENT_PROFILE``:
under a one-way / data-diode profile inbound file transfer is forbidden, so the
service still starts and serves ``/health`` but returns ``503`` on every ingest
route (fail-closed; see :func:`inbound_file_transfer_forbidden`).
"""

from __future__ import annotations

import json
import os

SERVICE_NAME = "watertwin-ingest"
SERVICE_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Deployment profile (edge / XiiD-ready topology). Mirrors watertwin-api.
#
# ``standard``      -- inbound file transfer to the ingest surface is permitted.
# ``one_way_diode`` -- a one-way / data-diode deployment. No inbound file
#                      transfer is permitted; the service starts and serves
#                      ``/health`` but returns 503 with a clear reason on every
#                      ingest route (fail-closed). An unknown profile fails
#                      closed to ``one_way_diode`` (the most restrictive posture).
# ---------------------------------------------------------------------------
STANDARD = "standard"
ONE_WAY_DIODE = "one_way_diode"
PROFILES = (STANDARD, ONE_WAY_DIODE)

#: Profiles under which the ingest service accepts no inbound file transfer.
_INBOUND_FORBIDDEN_PROFILES = frozenset({ONE_WAY_DIODE})


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def deployment_profile() -> str:
    """Return the normalized deployment profile (fail-closed on an unknown value)."""
    profile = (os.environ.get("DEPLOYMENT_PROFILE", STANDARD) or STANDARD).strip().lower()
    if profile not in PROFILES:
        return ONE_WAY_DIODE
    return profile


def inbound_file_transfer_forbidden() -> bool:
    """True when the active deployment profile forbids inbound file transfer.

    Under such a profile the service still starts and serves ``/health`` but
    every ingest route returns 503 (fail-closed).
    """
    return deployment_profile() in _INBOUND_FORBIDDEN_PROFILES


def inbound_forbidden_reason() -> str:
    """Human-readable reason returned on ingest routes when inbound is forbidden."""
    return (
        f"DEPLOYMENT_PROFILE={deployment_profile()} forbids inbound file transfer: "
        "the watertwin-ingest service is disabled in a one-way/data-diode "
        "deployment. Files must be delivered through the sanctioned one-way path."
    )


# ---------------------------------------------------------------------------
# Identity / RBAC (reuses the watertwin-api Keycloak OIDC contract verbatim).
# The env var names match watertwin-api so a deployment configures both the
# same way. Read at request time in app.auth, not cached here.
# ---------------------------------------------------------------------------
DEFAULT_TENANT_ID = os.environ.get("WATERTWIN_DEFAULT_TENANT_ID") or "s3m-default"
DEFAULT_FACILITY_ID = os.environ.get("WATERTWIN_DEFAULT_FACILITY_ID") or "S3M-DESAL-01"

# ---------------------------------------------------------------------------
# Content-addressed, write-once staging store.
# ---------------------------------------------------------------------------
#: Storage backend: ``local`` (filesystem, implemented) | ``s3`` (stubbed).
STORAGE_BACKEND = (os.environ.get("INGEST_STORAGE_BACKEND", "local") or "local").strip().lower()

#: Root directory for the local-filesystem backend.
STORAGE_ROOT = os.environ.get("INGEST_STORAGE_ROOT", "/data/ingest")

#: Bucket / container for the S3-compatible backend (stub).
STORAGE_S3_BUCKET = os.environ.get("INGEST_STORAGE_S3_BUCKET") or None
STORAGE_S3_ENDPOINT = os.environ.get("INGEST_STORAGE_S3_ENDPOINT") or None
STORAGE_S3_PREFIX = os.environ.get("INGEST_STORAGE_S3_PREFIX", "")

#: Streaming chunk size (bytes). Files are never loaded whole into memory.
STREAM_CHUNK_BYTES = _env_int("INGEST_STREAM_CHUNK_BYTES", 1024 * 1024)

# ---------------------------------------------------------------------------
# Scanner: pre-parse structural validation caps (config-driven).
# ---------------------------------------------------------------------------
#: The intake file classes and their per-class size caps (bytes). A declared
#: class not present here falls back to ``INGEST_DEFAULT_SIZE_CAP_BYTES``.
_DEFAULT_CLASS_SIZE_CAPS: dict[str, int] = {
    "lab_report": 25 * 1024 * 1024,
    "sensor_export": 100 * 1024 * 1024,
    "network_model": 50 * 1024 * 1024,
    "document": 25 * 1024 * 1024,
    "archive": 200 * 1024 * 1024,
    "generic": 10 * 1024 * 1024,
}

#: Default cap for an unknown declared class.
DEFAULT_SIZE_CAP_BYTES = _env_int("INGEST_DEFAULT_SIZE_CAP_BYTES", 10 * 1024 * 1024)


def class_size_caps() -> dict[str, int]:
    """Per-class size caps, overridable by ``INGEST_CLASS_SIZE_CAPS`` (JSON)."""
    caps = dict(_DEFAULT_CLASS_SIZE_CAPS)
    raw = os.environ.get("INGEST_CLASS_SIZE_CAPS")
    if raw:
        try:
            overrides = json.loads(raw)
        except json.JSONDecodeError:
            overrides = {}
        if isinstance(overrides, dict):
            for key, value in overrides.items():
                try:
                    caps[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue
    return caps


def size_cap_for(declared_class: str) -> int:
    """Return the byte cap for ``declared_class`` (default fallback if unknown)."""
    return class_size_caps().get(declared_class, DEFAULT_SIZE_CAP_BYTES)


#: Archive-bomb caps (structural, computed from archive metadata only).
ARCHIVE_MAX_COMPRESSION_RATIO = _env_float("INGEST_ARCHIVE_MAX_COMPRESSION_RATIO", 100.0)
ARCHIVE_MAX_NESTING_DEPTH = _env_int("INGEST_ARCHIVE_MAX_NESTING_DEPTH", 1)
ARCHIVE_MAX_TOTAL_UNCOMPRESSED_BYTES = _env_int(
    "INGEST_ARCHIVE_MAX_TOTAL_UNCOMPRESSED_BYTES", 500 * 1024 * 1024
)

# ---------------------------------------------------------------------------
# Antivirus hook: pluggable, no-op by default; ClamAV behind a config flag.
# ---------------------------------------------------------------------------
#: Antivirus backend: ``noop`` (default) | ``clamav``.
ANTIVIRUS_BACKEND = (os.environ.get("INGEST_ANTIVIRUS", "noop") or "noop").strip().lower()

#: ClamAV daemon (clamd) address, used only when ANTIVIRUS_BACKEND=clamav.
CLAMAV_HOST = os.environ.get("INGEST_CLAMAV_HOST", "127.0.0.1")
CLAMAV_PORT = _env_int("INGEST_CLAMAV_PORT", 3310)
CLAMAV_TIMEOUT_S = _env_float("INGEST_CLAMAV_TIMEOUT_S", 30.0)

# ---------------------------------------------------------------------------
# Per-tenant upload rate limiting (in-memory fixed window).
# ---------------------------------------------------------------------------
RATE_LIMIT_MAX_UPLOADS = _env_int("INGEST_RATE_LIMIT_MAX_UPLOADS", 60)
RATE_LIMIT_WINDOW_S = _env_float("INGEST_RATE_LIMIT_WINDOW_S", 60.0)

# ---------------------------------------------------------------------------
# watertwin-api HTTP integration (audit append). The ingest service has NO
# direct DB access; it posts hash-chained audit entries to the API over HTTP,
# authenticating with a provisioned service token.
# ---------------------------------------------------------------------------
API_BASE_URL = (os.environ.get("INGEST_API_URL", "http://watertwin-api:8000") or "").rstrip("/")

#: Audit-append path on the watertwin-api.
API_AUDIT_PATH = os.environ.get("INGEST_API_AUDIT_PATH", "/api/v1/ingest/audit")

#: Provisioned service token presented to the API (X-Ingest-Token). When unset
#: (dev/tests) the audit client falls back to an in-process local sink.
API_TOKEN = os.environ.get("INGEST_API_TOKEN") or None

#: Outbound HTTP timeout (seconds) for API calls.
API_TIMEOUT_S = _env_float("INGEST_API_TIMEOUT_S", 10.0)

# ---------------------------------------------------------------------------
# Advisory service-event bus (NATS). Same contract as watertwin-api.
# ---------------------------------------------------------------------------
#: NATS broker URL (e.g. ``nats://nats:4222``). Unset -> degraded (direct) mode.
NATS_URL = os.environ.get("NATS_URL") or None

#: Connect timeout (seconds) for the NATS client before degrading.
NATS_CONNECT_TIMEOUT = _env_float("NATS_CONNECT_TIMEOUT", 2.0)

# ---------------------------------------------------------------------------
# Pagination.
# ---------------------------------------------------------------------------
DEFAULT_PAGE_SIZE = _env_int("INGEST_DEFAULT_PAGE_SIZE", 50)
MAX_PAGE_SIZE = _env_int("INGEST_MAX_PAGE_SIZE", 200)
