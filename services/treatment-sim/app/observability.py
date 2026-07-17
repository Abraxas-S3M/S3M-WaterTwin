"""Observability wiring for treatment-sim.

Installs the shared observability stack (JSON logging, correlation ids, HTTP
metrics, ``/metrics`` and OpenTelemetry tracing) and publishes this service's
domain gauges:

* ``watertwin_buffer_depth`` (buffer=``jobs``) -- queued/running simulation
  jobs;
* ``watertwin_model_drift_ratio`` -- relative divergence between this service's
  discretized RO model and the canonical lumped analytical reference on the
  standard seawater feed (the same agreement the cross-check tests assert). A
  rising value flags model drift; both models are cheap/analytical so this is
  safe to evaluate at scrape time.

Read-only observation only; no control-write path exists.
"""

from __future__ import annotations

import logging
from typing import Any

from watertwin_observability import (
    BUFFER_DEPTH,
    MODEL_DRIFT,
    instrument_service,
    register_scrape_callback,
)

from . import config

logger = logging.getLogger("treatment-sim.observability")

SERVICE_NAME = config.SERVICE_NAME
_JOBS_BUFFER = "jobs"
_MODEL = "ro_baseline"

# Standard seawater reference feed used to gauge model drift (mirrors the
# cross-check suite's primary case).
_DRIFT_CASE = dict(
    feed_flow_m3h=config.SEAWATER_REFERENCE["flow_m3h"],
    feed_tds_mg_l=config.SEAWATER_REFERENCE["tds_mg_l"],
    feed_pressure_bar=config.SEAWATER_REFERENCE["pressure_bar"],
    membrane_area_m2=1200.0,
    temperature_c=config.SEAWATER_REFERENCE["temperature_c"],
)


def _rel(a: float, b: float) -> float:
    return abs(a - b) / b if b else abs(a - b)


def _model_drift() -> dict[str, float]:
    """Relative drift (service RO model vs analytical reference) per metric."""
    from watertwin_engineering import calculations

    from . import ro_model

    sim = ro_model.simulate_ro(**_DRIFT_CASE)
    ref = calculations.ro_performance(**_DRIFT_CASE)
    return {
        "recovery": _rel(sim.recovery, ref.recovery),
        "specific_energy": _rel(
            sim.specific_energy_kwh_m3, ref.specific_energy_kwh_m3
        ),
    }


def setup(app: Any, *, store: Any) -> None:
    """Instrument ``app`` and register buffer-depth + model-drift callbacks."""
    instrument_service(app, SERVICE_NAME, version=app.version)

    def _scrape() -> None:
        try:
            BUFFER_DEPTH.labels(service=SERVICE_NAME, buffer=_JOBS_BUFFER).set(
                store.buffer_depth()
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("buffer-depth gauge update failed", exc_info=True)
        try:
            for metric, drift in _model_drift().items():
                MODEL_DRIFT.labels(service=SERVICE_NAME, model=_MODEL, metric=metric).set(drift)
        except Exception:  # pragma: no cover - defensive
            logger.debug("model-drift gauge update failed", exc_info=True)

    register_scrape_callback(_scrape)

    # Prime the series so they are present on the very first scrape.
    BUFFER_DEPTH.labels(service=SERVICE_NAME, buffer=_JOBS_BUFFER).set(0)
    for metric in ("recovery", "specific_energy"):
        MODEL_DRIFT.labels(service=SERVICE_NAME, model=_MODEL, metric=metric).set(0.0)
