"""Configuration for the edge-gateway (read from the environment).

The edge-gateway sits at the plant edge, reads telemetry from a (synthetic here)
source and forwards it to the central ``watertwin-api`` ingest endpoint using a
durable, on-disk **store-and-forward** spool. Everything here is read-only with
respect to plant control: the gateway only reads telemetry and POSTs it upstream.
"""

from __future__ import annotations

import os
import socket


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
