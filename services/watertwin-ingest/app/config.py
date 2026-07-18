"""Configuration for watertwin-ingest (env-driven, documented defaults).

Nothing here is a control-write path. The knobs configure the hostile-input
firewall: per-tenant quotas, parser resource caps, retention, data residency,
and the deny-all egress allowlist. Every default is intentionally conservative
(fail-safe): quotas and caps are small enough to be safe out of the box and are
raised deliberately per deployment.
"""

from __future__ import annotations

import os

SERVICE_NAME = "watertwin-ingest"
SERVICE_VERSION = "0.1.0"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


# ---------------------------------------------------------------------------
# Deployment profile (mirrors services/watertwin-api DEPLOYMENT_PROFILE).
#
# ``standard``      -- inbound file ingestion is enabled.
# ``one_way_diode`` -- one-way / data-diode critical-infrastructure profile.
#                      Inbound ingestion is DISABLED (fail-closed) and the
#                      dashboard hides the ingestion nav item. An unknown value
#                      fails closed to one_way_diode.
# ---------------------------------------------------------------------------
DEPLOYMENT_PROFILE = _env_str("DEPLOYMENT_PROFILE", "standard").lower()

# ---------------------------------------------------------------------------
# Per-tenant quotas / rate limits. Exceeding any of these fails LOUDLY with a
# clear error (never silently drops data). Documented defaults below.
# ---------------------------------------------------------------------------
#: Max uploads accepted per tenant per rolling hour.
MAX_UPLOADS_PER_HOUR = _env_int("INGEST_MAX_UPLOADS_PER_HOUR", 100)
#: Max total stored bytes per tenant (across all retained uploads).
MAX_STORAGE_BYTES_PER_TENANT = _env_int(
    "INGEST_MAX_STORAGE_BYTES_PER_TENANT", 5 * 1024 * 1024 * 1024
)
#: Max concurrent parse jobs a single tenant may run at once.
MAX_CONCURRENT_PARSE_JOBS = _env_int("INGEST_MAX_CONCURRENT_PARSE_JOBS", 4)
#: Max size of a single uploaded file (bytes) accepted before parsing.
MAX_UPLOAD_BYTES = _env_int("INGEST_MAX_UPLOAD_BYTES", 100 * 1024 * 1024)

# ---------------------------------------------------------------------------
# Archive (zip) safety limits — anti zip-bomb.
# ---------------------------------------------------------------------------
#: Max cumulative *uncompressed* bytes an archive may expand to.
MAX_ARCHIVE_TOTAL_UNCOMPRESSED_BYTES = _env_int(
    "INGEST_MAX_ARCHIVE_UNCOMPRESSED_BYTES", 512 * 1024 * 1024
)
#: Max uncompressed:compressed ratio for any single member (compression bomb).
MAX_ARCHIVE_COMPRESSION_RATIO = _env_float("INGEST_MAX_ARCHIVE_RATIO", 120.0)
#: Max nesting depth of archives-within-archives.
MAX_ARCHIVE_DEPTH = _env_int("INGEST_MAX_ARCHIVE_DEPTH", 3)
#: Max number of members in a single archive.
MAX_ARCHIVE_MEMBERS = _env_int("INGEST_MAX_ARCHIVE_MEMBERS", 10_000)

# ---------------------------------------------------------------------------
# Parser sandbox resource caps — anti parser-DoS.
# ---------------------------------------------------------------------------
#: Wall-clock timeout (seconds) for a single parse job before it is killed.
PARSE_TIMEOUT_SECONDS = _env_float("INGEST_PARSE_TIMEOUT_SECONDS", 30.0)
#: Address-space (memory) cap (bytes) applied to a parse worker process.
PARSE_MEMORY_LIMIT_BYTES = _env_int(
    "INGEST_PARSE_MEMORY_LIMIT_BYTES", 512 * 1024 * 1024
)

# ---------------------------------------------------------------------------
# Retention. Deletion removes file CONTENT; audit entries are immutable and
# survive deletion (see docs/deployment/data-residency.md and retention.py).
# ---------------------------------------------------------------------------
#: Default retention period (days) for uploaded file content per tenant.
DEFAULT_RETENTION_DAYS = _env_int("INGEST_DEFAULT_RETENTION_DAYS", 90)

# ---------------------------------------------------------------------------
# Data residency (regulated jurisdictions incl. Saudi critical infrastructure).
# The residency region controls WHERE uploaded content is stored. It is set per
# tenant; this is the platform default when a tenant has no explicit residency.
# ---------------------------------------------------------------------------
#: Default storage residency region (ISO-3166 alpha-2 or a cloud region tag).
DEFAULT_RESIDENCY_REGION = _env_str("INGEST_DEFAULT_RESIDENCY_REGION", "SA")

# ---------------------------------------------------------------------------
# Egress allowlist. The parser workers have DENY-ALL egress by default; only the
# S3M endpoint and the watertwin-api endpoint are reachable. OT networks, MQTT
# and OPC UA are ALWAYS denied, even if erroneously added to the allowlist.
# ---------------------------------------------------------------------------
#: Base URL of the S3M platform endpoint (the only external egress target).
S3M_ENDPOINT_URL = _env_str("INGEST_S3M_ENDPOINT_URL", "https://s3m.internal:443")
#: Base URL of the watertwin-api endpoint (in-cluster advisory API).
WATERTWIN_API_URL = _env_str("INGEST_WATERTWIN_API_URL", "http://watertwin-api:8000")
