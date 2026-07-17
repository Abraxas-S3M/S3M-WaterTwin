"""Configuration for watertwin-api."""

from __future__ import annotations

import os

SERVICE_NAME = "watertwin-api"
SERVICE_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Deployment profile (edge / XiiD-ready topology).
#
# ``standard``       -- the platform may pull telemetry from a real OT feed via
#                       the read-only OT connectors (OPC UA / Modbus / historian
#                       REST or SQL). These are still strictly read-only, but the
#                       *connection* is initiated by the platform toward the OT
#                       side.
# ``one_way_diode``  -- a one-way / data-diode profile: the edge gateway PUSHES
#                       telemetry to the platform and the platform NEVER initiates
#                       a connection toward the OT side. Any platform->OT request
#                       code path is disabled at startup (fail-closed). Only the
#                       synthetic source and gateway-pushed / file-drop feeds are
#                       permitted. See docs/deployment/edge-xiid-reference.md.
# ---------------------------------------------------------------------------
DEPLOYMENT_PROFILE = os.environ.get("DEPLOYMENT_PROFILE", "standard").strip().lower()

# Base URL of the hydraulic-sim service (its own container).
HYDRAULIC_SIM_URL = os.environ.get("HYDRAULIC_SIM_URL", "http://hydraulic-sim:8100")

# Recommendation store (shared store pattern; JSON-file backed by default).
RECOMMENDATION_STORE_PATH = os.environ.get(
    "WATERTWIN_RECO_STORE",
    os.path.join(os.path.dirname(__file__), "..", "data", "recommendations.json"),
)

# Work-order store (JSON-file backed by default; mirrors the recommendation store).
WORK_ORDER_STORE_PATH = os.environ.get(
    "WATERTWIN_WORK_ORDER_STORE",
    os.path.join(os.path.dirname(__file__), "..", "data", "work-orders.json"),
)

# ---------------------------------------------------------------------------
# CMMS (maintenance system of record) integration.
#
# The platform talks to a CMMS through a pluggable adapter (app/cmms/). The
# default adapter is STRICTLY READ-ONLY: it pulls work orders + asset history
# only. A write-back adapter -- which creates a CMMS *ticket* for an
# operator-approved work order -- is enabled ONLY when CMMS_WRITE_BACK_ENABLED
# is true. A CMMS ticket is a business-system record, NEVER an OT/control path,
# and is only ever created after operator approval.
# ---------------------------------------------------------------------------


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


#: Enable write-back of operator-approved work orders as CMMS tickets. Default
#: false (read-only). Even when true this is a ticket path, never a control path.
CMMS_WRITE_BACK_ENABLED = _env_bool("CMMS_WRITE_BACK_ENABLED", False)

#: Human-readable name of the CMMS system of record.
CMMS_SYSTEM_NAME = os.environ.get("CMMS_SYSTEM", "synthetic-cmms")

# CORS origins allowed to call this API (the dashboard).
CORS_ORIGINS = os.environ.get("WATERTWIN_CORS_ORIGINS", "*").split(",")

# ---------------------------------------------------------------------------
# Compliance limits config store (A1 config store).
#
# Per-parameter regulatory limits (e.g. turbidity, conductivity, chlorine
# residual) are held in the A1 config store. They ship with documented defaults
# and are deployment-configurable: point ``WATERTWIN_COMPLIANCE_LIMITS_PATH`` at
# a JSON file, or set ``WATERTWIN_COMPLIANCE_LIMITS`` to an inline JSON array of
# limit objects, to override/extend the defaults. Nothing here is a control-write
# path; the limits only drive advisory compliance screening + reports.
# ---------------------------------------------------------------------------

#: Optional path to a JSON file of compliance-limit overrides.
COMPLIANCE_LIMITS_PATH = os.environ.get("WATERTWIN_COMPLIANCE_LIMITS_PATH") or None

#: Optional inline JSON array of compliance-limit overrides.
COMPLIANCE_LIMITS_JSON = os.environ.get("WATERTWIN_COMPLIANCE_LIMITS") or None

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
# Multi-tenant / multi-facility scoping.
#
# Every canonical record and persisted row is scoped to a (tenant, facility)
# pair. The platform historically modelled a single facility with no explicit
# tenant boundary; that pre-existing data is treated as belonging to the default
# tenant/facility below so upgrades are non-breaking (the store backfills NULL
# scopes to these defaults on connect). These defaults are also used as the
# implicit scope for callers whose token carries no explicit tenant/facility
# membership (e.g. the dev bypass and legacy single-facility tokens).
# ---------------------------------------------------------------------------
DEFAULT_TENANT_ID = os.environ.get("WATERTWIN_DEFAULT_TENANT_ID") or "s3m-default"
DEFAULT_FACILITY_ID = os.environ.get("WATERTWIN_DEFAULT_FACILITY_ID") or "S3M-DESAL-01"

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
