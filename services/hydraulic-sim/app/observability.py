"""Observability wiring for hydraulic-sim.

Installs the shared observability stack (JSON logging, correlation ids, HTTP
metrics, ``/metrics`` and OpenTelemetry tracing) and publishes this service's
buffer-depth gauge: the number of simulation jobs that are queued or running
(i.e. the depth of the async what-if work buffer).

Read-only observation only; no control-write path exists.
"""

from __future__ import annotations

import logging
from typing import Any

from simulation_contracts import JobState

from watertwin_observability import (
    BUFFER_DEPTH,
    instrument_service,
    register_scrape_callback,
)

from . import config

logger = logging.getLogger("hydraulic-sim.observability")

_ACTIVE_STATES = {JobState.queued, JobState.running}
_JOBS_BUFFER = "jobs"


def setup(app: Any, *, store: Any) -> None:
    """Instrument ``app`` and register the buffer-depth scrape callback."""
    instrument_service(app, config.SERVICE_NAME, version=config.SERVICE_VERSION)
    service = config.SERVICE_NAME

    def _scrape() -> None:
        try:
            depth = sum(1 for job in store.list() if job.state in _ACTIVE_STATES)
            BUFFER_DEPTH.labels(service=service, buffer=_JOBS_BUFFER).set(depth)
        except Exception:  # pragma: no cover - defensive
            logger.debug("buffer-depth gauge update failed", exc_info=True)

    register_scrape_callback(_scrape)
    BUFFER_DEPTH.labels(service=service, buffer=_JOBS_BUFFER).set(0)
