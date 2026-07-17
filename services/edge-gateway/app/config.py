"""Configuration for the edge-gateway (all env-driven).

The gateway is OUTBOUND-ONLY: it dials the watertwin-api ingest endpoint and
never opens an inbound listener. OT source selection mirrors the watertwin-api
env contract so the shared :func:`ot_ingestion.sources.resolve_source` resolver
(with graceful synthetic fallback) can be reused unchanged.
"""Configuration for the edge-gateway (read from the environment).

The edge-gateway sits at the plant edge, reads telemetry from a (synthetic here)
source and forwards it to the central ``watertwin-api`` ingest endpoint using a
durable, on-disk **store-and-forward** spool. Everything here is read-only with
respect to plant control: the gateway only reads telemetry and POSTs it upstream.
"""

from __future__ import annotations

import os
import socket

SERVICE_NAME = "edge-gateway"
SERVICE_VERSION = "0.1.0"

#: Stable identifier for this gateway instance (used for source-health tracking
#: on the API side). Defaults to the container/host name.
GATEWAY_ID = os.environ.get("EDGE_GATEWAY_ID") or socket.gethostname()

FACILITY_ID = os.environ.get("EDGE_GATEWAY_FACILITY_ID", "S3M-DESAL-01")
TRAIN_ID = os.environ.get("EDGE_GATEWAY_TRAIN_ID", "RO-TRAIN-001")

# ---------------------------------------------------------------------------
# Outbound push target (watertwin-api ingest endpoint).
# ---------------------------------------------------------------------------
#: Base URL of the watertwin-api (its own container / host).
API_BASE_URL = os.environ.get("EDGE_GATEWAY_API_URL", "http://watertwin-api:8000")
#: Ingest path on the API (outbound POST target).
INGEST_PATH = os.environ.get("EDGE_GATEWAY_INGEST_PATH", "/api/v1/ingestion/telemetry")
#: Optional bearer token presented to the API (service credential).
API_TOKEN = os.environ.get("EDGE_GATEWAY_API_TOKEN") or None
#: Per-request outbound timeout (seconds).
HTTP_TIMEOUT_S = float(os.environ.get("EDGE_GATEWAY_HTTP_TIMEOUT_S", "10"))

# ---------------------------------------------------------------------------
# Local encrypted store-and-forward buffer.
# ---------------------------------------------------------------------------
#: SQLite buffer file path. Persisted on a volume so it survives restarts.
BUFFER_PATH = os.environ.get("EDGE_GATEWAY_BUFFER_PATH", "/data/edge-buffer.db")
#: Encryption key/passphrase for the at-rest buffer. Any string; a stable
#: Fernet key is derived from it. MUST be set (and kept stable) for the buffer
#: to survive restarts encrypted; when unset a random ephemeral key is used and
#: previously-buffered rows become unreadable after a restart (logged loudly).
BUFFER_KEY = os.environ.get("EDGE_GATEWAY_BUFFER_KEY") or None
#: Max readings drained from the buffer and pushed per forward attempt.
FORWARD_BATCH_SIZE = int(os.environ.get("EDGE_GATEWAY_FORWARD_BATCH_SIZE", "500"))
#: Hard cap on buffered readings; oldest are dropped past this (backpressure).
BUFFER_MAX_ROWS = int(os.environ.get("EDGE_GATEWAY_BUFFER_MAX_ROWS", "500000"))

# ---------------------------------------------------------------------------
# Collection loop.
# ---------------------------------------------------------------------------
#: Seconds between successive source polls.
POLL_INTERVAL_S = float(os.environ.get("EDGE_GATEWAY_POLL_INTERVAL_S", "5"))

#: Liveness heartbeat file, touched after every collection cycle. Since the
#: gateway binds no port, the container healthcheck asserts this file is fresh.
HEARTBEAT_PATH = os.environ.get("EDGE_GATEWAY_HEARTBEAT_PATH", "/tmp/edge-gateway.heartbeat")

# ---------------------------------------------------------------------------
# Data-quality thresholds.
# ---------------------------------------------------------------------------
#: A reading whose timestamp is older than this (seconds) is flagged ``stale``.
STALENESS_LIMIT_S = float(os.environ.get("EDGE_GATEWAY_STALENESS_LIMIT_S", "60"))
#: Consecutive identical samples before a signal is flagged ``frozen``.
FROZEN_LIMIT = int(os.environ.get("EDGE_GATEWAY_FROZEN_LIMIT", "10"))
#: Absolute change below this (in engineering units) is within the deadband;
#: such readings are flagged ``deadband`` (unchanged / not significant).
DEADBAND = float(os.environ.get("EDGE_GATEWAY_DEADBAND", "0.0"))

# ---------------------------------------------------------------------------
# OT source selection (mirrors the watertwin-api read-only source contract).
# Reused verbatim by ot_ingestion.sources.resolve_source (graceful fallback to
# synthetic when a configured real source is unreachable/misconfigured).
# ---------------------------------------------------------------------------
OT_SOURCE = os.environ.get("OT_SOURCE", "synthetic").strip().lower()
OT_TAG_MAP = os.environ.get("OT_TAG_MAP") or None

# --- OPC UA (asyncua client, read-only) ------------------------------------
OT_OPCUA_ENDPOINT = os.environ.get("OT_OPCUA_ENDPOINT") or None
OT_OPCUA_NODE_IDS = [
    n.strip() for n in os.environ.get("OT_OPCUA_NODE_IDS", "").split(",") if n.strip()
]

# --- Modbus (pymodbus client, read-only function codes only) ---------------
OT_MODBUS_HOST = os.environ.get("OT_MODBUS_HOST") or None
OT_MODBUS_PORT = int(os.environ.get("OT_MODBUS_PORT", "502"))
OT_MODBUS_UNIT = int(os.environ.get("OT_MODBUS_UNIT", "1"))
OT_MODBUS_REGISTERS = [
    r.strip() for r in os.environ.get("OT_MODBUS_REGISTERS", "").split(",") if r.strip()
]

# --- Historian (read-only REST / SQL / CSV pull) ---------------------------
OT_HISTORIAN_KIND = os.environ.get("OT_HISTORIAN_KIND", "csv").strip().lower()
OT_HISTORIAN_CSV_PATH = os.environ.get("OT_HISTORIAN_CSV_PATH") or None
OT_HISTORIAN_URL = os.environ.get("OT_HISTORIAN_URL") or None
OT_HISTORIAN_DSN = os.environ.get("OT_HISTORIAN_DSN") or None
OT_HISTORIAN_QUERY = os.environ.get("OT_HISTORIAN_QUERY") or None

def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


SERVICE_NAME = "edge-gateway"
SERVICE_VERSION = "0.1.0"

#: Stable identifier for this gateway. Used as the batch-id prefix so ingest
#: idempotency keys are globally unique per gateway.
GATEWAY_ID = os.environ.get("EDGE_GATEWAY_ID") or f"edge-{socket.gethostname()}"

#: Base URL of the central watertwin-api the gateway forwards telemetry to.
API_URL = os.environ.get("EDGE_API_URL", "http://watertwin-api:8000").rstrip("/")

#: Ingest path on the central API.
INGEST_PATH = os.environ.get("EDGE_INGEST_PATH", "/api/v1/ingestion/telemetry")

#: Provisioned ingest token presented as the ``X-Ingest-Token`` header. Empty
#: when the upstream API runs with auth disabled (local dev / chaos drill).
INGEST_TOKEN = os.environ.get("EDGE_INGEST_TOKEN") or None

#: Durable spool directory (mount a volume here). Un-forwarded batches persist
#: as files so a crash/restart never loses data.
SPOOL_DIR = os.environ.get("EDGE_SPOOL_DIR", "/data/spool")

#: Seconds between produced telemetry batches.
BATCH_INTERVAL_S = _float("EDGE_BATCH_INTERVAL_S", 1.0)

#: Poll interval (seconds) for the forwarder loop when it has work / is retrying.
FORWARD_INTERVAL_S = _float("EDGE_FORWARD_INTERVAL_S", 0.5)

#: Max seconds to back off between failed forward attempts.
FORWARD_MAX_BACKOFF_S = _float("EDGE_FORWARD_MAX_BACKOFF_S", 10.0)

#: HTTP timeout for a forward attempt.
FORWARD_TIMEOUT_S = _float("EDGE_FORWARD_TIMEOUT_S", 5.0)

#: Stop producing after this many batches (0 = run forever). Handy for finite
#: load / chaos runs.
MAX_BATCHES = _int("EDGE_MAX_BATCHES", 0)

#: Whether the producer loop is enabled (the forwarder always drains the spool).
PRODUCE_ENABLED = os.environ.get("EDGE_PRODUCE_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
