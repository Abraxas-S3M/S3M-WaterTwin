"""Configuration for watertwin-api."""

from __future__ import annotations

import os

SERVICE_NAME = "watertwin-api"
SERVICE_VERSION = "0.1.0"

# Base URL of the hydraulic-sim service (its own container).
HYDRAULIC_SIM_URL = os.environ.get("HYDRAULIC_SIM_URL", "http://hydraulic-sim:8100")

# Recommendation store (shared store pattern; JSON-file backed by default).
RECOMMENDATION_STORE_PATH = os.environ.get(
    "WATERTWIN_RECO_STORE",
    os.path.join(os.path.dirname(__file__), "..", "data", "recommendations.json"),
)

# CORS origins allowed to call this API (the dashboard).
CORS_ORIGINS = os.environ.get("WATERTWIN_CORS_ORIGINS", "*").split(",")

# Durable store (TimescaleDB/Postgres). When unset the store runs purely in
# memory and degrades gracefully; nothing here is ever a control-write path.
DATABASE_URL = os.environ.get("WATERTWIN_DATABASE_URL") or None

# Provisioned shared token an edge gateway presents (X-Ingest-Token header) to
# the telemetry ingest path. When unset, ingest falls back to role-based auth
# (see app.auth.require_ingest). Read at request time in app.auth, not here.
INGEST_TOKEN = os.environ.get("WATERTWIN_INGEST_TOKEN") or None

# ---------------------------------------------------------------------------
# Advisory service-event bus (NATS).
#
# Service events (telemetry-ingested, alert-raised, workorder-created,
# config-published, audit-appended) are published to a NATS bus so other
# services can react/project them. The bus is ADVISORY / NOTIFICATION ONLY: it
# never carries a control command (enforced by the subject guard in
# ``watertwin_events``). When ``NATS_URL`` is unset or the broker is unreachable
# the bus degrades gracefully -- it logs, counts a metric, and falls back to
# direct in-process delivery so the API keeps working. No event is ever a
# control-write path.
# ---------------------------------------------------------------------------

#: NATS broker URL (e.g. ``nats://nats:4222``). Unset -> degraded (direct) mode.
NATS_URL = os.environ.get("NATS_URL") or None

#: Connect timeout (seconds) for the NATS client before degrading.
NATS_CONNECT_TIMEOUT = float(os.environ.get("NATS_CONNECT_TIMEOUT", "2.0"))

# ---------------------------------------------------------------------------
# Telemetry source selection (read-only OT connectors).
#
# The platform ingests telemetry from a pluggable, strictly READ-ONLY source.
# The default is the built-in synthetic plant; a deployment may point at a real
# OT feed (OPC UA / Modbus / historian). If a real source is configured but
# unreachable the service logs and FALLS BACK to synthetic (never crashes) and
# surfaces the active source + fallback state in /health. No source ever writes
# to a control system.
# ---------------------------------------------------------------------------

#: Active telemetry source: synthetic | opcua | modbus | historian.
OT_SOURCE = os.environ.get("OT_SOURCE", "synthetic").strip().lower()

#: Tag map (name under data/tag-maps/, or a path) used to normalize a real OT
#: feed onto the canonical model. Required for opcua/modbus/historian sources.
OT_TAG_MAP = os.environ.get("OT_TAG_MAP") or None

# --- OPC UA (asyncua client, read-only) ------------------------------------
OT_OPCUA_ENDPOINT = os.environ.get("OT_OPCUA_ENDPOINT") or None
#: Comma-separated OPC UA NodeIds to read (each NodeId is the customer tag).
OT_OPCUA_NODE_IDS = [
    n.strip() for n in os.environ.get("OT_OPCUA_NODE_IDS", "").split(",") if n.strip()
]

# --- Modbus (pymodbus client, read-only function codes only) ---------------
OT_MODBUS_HOST = os.environ.get("OT_MODBUS_HOST") or None
OT_MODBUS_PORT = int(os.environ.get("OT_MODBUS_PORT", "502"))
OT_MODBUS_UNIT = int(os.environ.get("OT_MODBUS_UNIT", "1"))
#: Register spec list "<kind>:<address>[:<count>]" (kind = coil|discrete|
#: holding|input), e.g. "holding:0,holding:1,input:0". The customer tag for
#: each register is "<kind>:<address>".
OT_MODBUS_REGISTERS = [
    r.strip() for r in os.environ.get("OT_MODBUS_REGISTERS", "").split(",") if r.strip()
]

# --- Historian (read-only REST / SQL / CSV pull) ---------------------------
#: Historian access kind: csv | rest | sql.
OT_HISTORIAN_KIND = os.environ.get("OT_HISTORIAN_KIND", "csv").strip().lower()
OT_HISTORIAN_CSV_PATH = os.environ.get("OT_HISTORIAN_CSV_PATH") or None
OT_HISTORIAN_URL = os.environ.get("OT_HISTORIAN_URL") or None
OT_HISTORIAN_DSN = os.environ.get("OT_HISTORIAN_DSN") or None
#: A read-only SELECT statement returning (tag, value[, timestamp, quality]).
OT_HISTORIAN_QUERY = os.environ.get("OT_HISTORIAN_QUERY") or None
