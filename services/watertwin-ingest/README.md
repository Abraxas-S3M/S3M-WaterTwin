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
Templated spreadsheet ingestion for the S3M-WaterTwin configuration workbench.

This service removes the three highest-volume hand-entry burdens in the workbench
by letting an operator download a template, fill it in, upload it, and review a
diff before anything is applied:

| Template            | Parser                        | Provenance          |
| ------------------- | ----------------------------- | ------------------- |
| Equipment specs     | `app/parsers/equipment.py`    | `vendor_specified`  |
| OT tag mapping      | `app/parsers/tag_mapping.py`  | `customer_supplied` |
| Lab methods         | `app/parsers/lab.py`          | `customer_supplied` |

## Safety posture

This service is **read-only to OT and decision-support only**. It parses uploaded
files into an in-memory, reviewable diff (`ParseReport`); it never connects to, or
writes to, any SCADA / PLC / OPC UA / MQTT system, and it issues no control
commands. Uploaded spreadsheets are read defensively:

- `.xlsx` is opened with **openpyxl in `read_only` + `data_only` mode** — only
  cached cell *values* are read and macros are never executed.
- **`.xlsm` (macro-enabled) workbooks are rejected outright**, before any parsing.
- CSV **encoding is detected with an explicit documented fallback** (`cp1252`) and
  a warning whenever the encoding had to be guessed — text is never silently
  mangled.
- Any cell that could be interpreted as a spreadsheet formula (`=`, `+`, `-`, `@`,
  TAB, CR) is neutralised on *export* by the shared `escape_formula` helper
  (`app/parsers/tabular.py`) to prevent CSV-injection.

## Validation

Every numeric field is range-checked against the engineering plausibility bounds
in `packages/watertwin_engineering` (`SPECIFICATION_RANGES`) — never hardcoded in
the parser. An out-of-range value (a negative NPSHr, an efficiency above `1.0`, a
`10,000 m` head) is surfaced as a validation error in the diff, naming the
specific range it violated, instead of being silently imported. Bad rows never
discard the good ones; problems are collected per row with 1-based row numbers.

Units are taken from an explicit `unit` column (tag mapping, lab) or a documented
template default embedded in the numeric header (equipment). Units are never
inferred; an ambiguous / unit-bearing numeric cell is warned and left unparsed.

## Templates

The downloadable templates in `app/templates/*.csv` are **generated from the same
column contract the parser enforces**, so they can never drift. Regenerate them
with:

```bash
python -c "from app.parsers import write_templates; write_templates()"
```

`tests/test_templates.py` fails if a committed template drifts from its contract.

## Running the tests

```bash
cd services/watertwin-ingest
python -m pytest -q
```
