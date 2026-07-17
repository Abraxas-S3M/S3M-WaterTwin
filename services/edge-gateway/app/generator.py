"""Synthetic telemetry generator (read-only edge feed).

Produces batches of canonical :class:`~canonical_water_model.TelemetryReading`
records for a small fixed set of RO-train assets. This stands in for a real
read-only OT feed at the plant edge; it only *reads*/synthesizes telemetry and
never writes to any control system.
"""

from __future__ import annotations

import math
from typing import Any

from canonical_water_model import DataProvenance, TelemetryReading, now_iso

#: (asset_id, metric, unit, baseline value) tuples the edge feed emits per tick.
_SIGNALS: tuple[tuple[str, str, str, float], ...] = (
    ("PU-PROD-1", "vibration_mm_s", "mm/s", 2.8),
    ("PU-PROD-1", "winding_temp_c", "degC", 62.0),
    ("PU-PROD-2", "vibration_mm_s", "mm/s", 3.1),
    ("PU-PROD-2", "discharge_pressure_bar", "bar", 61.5),
    ("RO-TRAIN-001", "permeate_flow_m3h", "m3/h", 420.0),
    ("RO-TRAIN-001", "feed_pressure_bar", "bar", 58.0),
    ("RO-TRAIN-001", "permeate_tds_mg_l", "mg/L", 240.0),
)

#: Number of readings in each produced batch.
BATCH_SIZE = len(_SIGNALS)


def build_readings(tick: int) -> list[dict[str, Any]]:
    """Build one batch of canonical readings for ``tick`` (JSON-ready dicts).

    Values wobble deterministically around their baseline so successive batches
    differ, but the shape/units are stable and provenance is always recorded as
    ``synthetic`` -- these are never measured plant data.
    """
    timestamp = now_iso()
    readings: list[dict[str, Any]] = []
    for index, (asset_id, metric, unit, baseline) in enumerate(_SIGNALS):
        wobble = 0.03 * baseline * math.sin((tick + index) / 3.0)
        readings.append(
            TelemetryReading(
                asset_id=asset_id,
                metric=metric,
                value=round(baseline + wobble, 4),
                unit=unit,
                timestamp=timestamp,
                provenance=DataProvenance.synthetic,
                quality="good",
            ).model_dump(mode="json")
        )
    return readings
