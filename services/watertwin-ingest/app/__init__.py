"""watertwin-ingest: bulk file-import staging service.

This service ingests two large-file classes that do not arrive over the live OT
telemetry path:

* **historian time-series exports** (``.csv`` / ``.parquet``, up to ~500 MB), and
* **customer geospatial layers** (``.geojson`` / zipped shapefile).

Every parser here is **read-only with respect to the plant**: it reads a file the
customer supplied, resolves it against configuration, writes the result to a
*staging* area, and emits an **approval proposal**. Nothing is streamed straight
into the analytic store, no control system is ever written, and importing a file
never promotes an analytic from ``preliminary`` to ``calibrated`` -- only the
documented, engineer-signed validation process does that.
"""

from __future__ import annotations

__all__: list[str] = []
