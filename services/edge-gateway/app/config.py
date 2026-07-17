"""Configuration for the edge-gateway (all env-driven).

The gateway is OUTBOUND-ONLY: it dials the watertwin-api ingest endpoint and
never opens an inbound listener. OT source selection mirrors the watertwin-api
env contract so the shared :func:`ot_ingestion.sources.resolve_source` resolver
(with graceful synthetic fallback) can be reused unchanged.
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
