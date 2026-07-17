"""Service configuration for hydraulic-sim."""

from __future__ import annotations

import os

SERVICE_NAME = "hydraulic-sim"
SERVICE_VERSION = "0.1.0"

# Where async job state is persisted (shared store pattern). A JSON file keeps the
# store simple and container-friendly; the same interface can be backed by Redis
# or Postgres in later phases without changing callers.
JOB_STORE_PATH = os.environ.get(
    "HYDRAULIC_SIM_JOB_STORE",
    os.path.join(os.path.dirname(__file__), "..", "data", "jobs.json"),
)

# Absolute path to the EPANET .inp network model (optional override).
NETWORK_INP_PATH = os.environ.get("HYDRAULIC_SIM_INP")

# Control boundary: this service is advisory / read-only and must never write to
# any control system. These values are surfaced verbatim on /health.
CONTROL_MODE = os.environ.get("HYDRAULIC_SIM_CONTROL_MODE", "advisory")
