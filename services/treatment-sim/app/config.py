"""Service configuration and known-good reference feed presets."""

from __future__ import annotations

import os

SERVICE_NAME = "treatment-sim"

# Standard seawater RO reference feed used for health checks and test baselines.
SEAWATER_REFERENCE = {
    "flow_m3h": 100.0,
    "tds_mg_l": 35000.0,
    "temperature_c": 25.0,
    "pressure_bar": 60.0,
}

# Cross-check tolerance: the WaterTAP/analytical service result must agree with
# watertwin.calculations within this relative tolerance or it is a bug signal.
CROSS_CHECK_REL_TOLERANCE = float(
    os.environ.get("TREATMENT_SIM_CROSS_CHECK_TOL", "0.15")
)

HOST = os.environ.get("TREATMENT_SIM_HOST", "0.0.0.0")
PORT = int(os.environ.get("TREATMENT_SIM_PORT", "8080"))
