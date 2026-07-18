# watertwin-ingest

Bulk **file-import staging** service for the two large-file classes that do not
arrive over the live OT telemetry path:

- **historian time-series exports** — `.csv` / `.parquet`, up to ~500 MB
- **customer geospatial layers** — `.geojson` / zipped shapefile

## What it does (and deliberately does not)

Every parser is **read-only with respect to the plant**. It reads a
customer-supplied file, resolves it against configuration, writes the result to
a **staging area**, and emits a human-**approval proposal**. Nothing streams
straight into the analytic store; no control system (SCADA / PLC / OPC UA /
MQTT) is ever written.

Critically, **importing a file never promotes an analytic from `preliminary` to
`calibrated`.** Only the documented validation process, with a named engineer's
sign-off, does that. Imported historian data is labelled `customer_measured` and
imported geospatial data `customer_supplied` — labels that are distinct from the
canonical `measured`/`calibrated` provenance and can never be mistaken for it.

Out of scope by design: **no gap filling, no resampling, no interpolation.** We
import what is there and report what is missing.

### `app/parsers/historian.py`

- Streamed/chunked (`csv` row-by-row, Parquet by record batch) → bounded memory.
- Expected shape: `tag, timestamp, value, [quality], [timezone]`.
- Tags resolved through the shared tag-mapping config; **unmapped tags are
  reported, never guessed**.
- **Timezones are explicit.** A timestamp must carry an offset, a per-row
  `timezone`, or fall under a declared file-level timezone. Naive/ambiguous
  timestamps are a warning and their rows go to *unparsed* — UTC is never
  assumed on plant data.

### `app/parsers/gis.py`

- XML parsed with `defusedxml` (DTDs/entities forbidden) → no XXE surface.
- Zip members are path-sanitized; a traversal member rejects the whole archive.
- CRS is explicit: taken from an argument, the GeoJSON `crs` member, or the
  shapefile `.prj`; geometry is reprojected to the platform CRS
  (`EPSG:4326`) and **both** CRSs are recorded.
- Geometry is validated (via `network_twin.validate_geometry`) before staging;
  invalid geometry is reported, never silently repaired.

## Tests

```bash
cd services/watertwin-ingest
python -m pytest -q                 # fast suite
python -m pytest -q -m slow         # includes the ~500 MB streaming test
```
