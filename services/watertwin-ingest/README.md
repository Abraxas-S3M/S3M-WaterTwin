# watertwin-ingest

Customer-document ingestion for the S3M-WaterTwin Operations Assistant.

This service performs **text extraction only** from operator-supplied O&M
manuals, SOPs and design-basis documents so the Operations Assistant can ground
its answers in the customer's own documents alongside the platform-seeded corpus.

It is deliberately narrow and defensive — it is read-only to its inputs and
never executes active content:

- `.pdf` — text layer only (`pypdf`). No JavaScript execution, no embedded-file
  extraction, no form-field evaluation. A scanned / image-only PDF (no text
  layer) is reported as `unparsed` with a clear reason. **No OCR** is performed.
- `.docx` — paragraph + heading text (`python-docx`). Macros are never executed.
- `.docm` (and other macro-enabled Office formats) — **rejected**.
- `.md` / `.txt` — read directly as UTF-8.
- Malformed input — reported as `parse_failed`; never crashes, never hangs.

Extracted text is split into stable, deterministic chunks. Every chunk carries
its source document id, page (PDF) or section (heading), and character offsets
so a downstream citation can resolve to a real location in a real file.

The parsed output (`ParsedDocument.as_store_chunks()`) is consumed by the
`watertwin-api` `DocumentStore`, where each customer document is tenant-scoped
and only becomes retrievable by the Assistant after it passes the approval gate.

## Develop / test

```bash
pip install -r requirements.txt
python -m pytest -q
ruff check .
```

## Safety posture

Read-only, decision-support only. Nothing in this service writes to any control
system (SCADA / PLC / OPC UA / MQTT) or issues any command.
A **hardened, tenant-isolated, advisory** file/document ingestion service. It is
the *hostile-input firewall* in front of the rest of S3M-WaterTwin: every
uploaded file is untrusted, so every parser runs behind a stack of security
controls. The service is **read-only to OT** (no SCADA/PLC/OPC UA/MQTT path) and
has **no control-write path** anywhere.

## Safety posture (never weakened here)

- `control_mode = "advisory"`, `operator_approval_required = true`,
  `control_write_enabled = false` — stamped on every response and audit entry.
- Parser workers have **deny-all egress**; OT/MQTT/OPC UA are always denied.
- Uploaded content is inert **data**, never instructions: ingestion takes no
  action, changes no approval, and never mutates provenance (prompt-injection
  safe).

## Controls (each mapped to a threat-model row + test)

| Control | Module | Threat-model row |
|---------|--------|------------------|
| Malware scan (EICAR/AV, fail-closed) | `app/scanning.py` | T1 |
| Zip-bomb limits (ratio / depth / size / members) | `app/archives.py` | T2 |
| XXE / external-entity / entity-expansion safe XML | `app/xml_safe.py` | T3 |
| XSLT stylesheet-PI rejection | `app/xml_safe.py` | T4 |
| CSV formula-injection escaping on export | `app/csv_safe.py` | T5 |
| Archive path-traversal (Zip Slip) prevention | `app/archives.py` | T6 |
| Parser DoS sandbox (timeout + memory cap) | `app/limits.py` | T7 |
| Prompt-injection inertness | `app/provenance.py` | T8 |
| Poisoned-config engineering validation | `app/engineering_validation.py` | T9 |
| Cross-tenant isolation (read/list/content) | `app/tenancy.py` | T10 |
| Deny-all worker egress / no OT reachability | `app/egress.py` | T11 |
| Tamper-evident hash-chained audit | `app/audit.py` | T12 |
| Per-tenant quotas (uploads/storage/concurrency) | `app/quotas.py` | quotas |
| Per-tenant retention + deletion behaviour | `app/retention.py` | retention |
| Per-tenant data residency (Saudi CI) | `app/residency.py` | residency |
| One-way-diode gate (ingestion off, nav hidden) | `app/deployment.py` | invariant |

The authoritative threat model and control→test mapping is
[`security/threat-model-ingestion.md`](../../security/threat-model-ingestion.md);
the blocking test suite is under [`security/tests/`](../../security/tests/).

## Container hardening

See `Dockerfile` and `deploy/`:

- distroless runtime image — **no shell**, non-root (UID 65532)
- `readOnlyRootFilesystem`, all capabilities dropped, `allowPrivilegeEscalation:
  false`, seccomp profile (`deploy/seccomp.json`)
- deny-all egress `NetworkPolicy` (`deploy/networkpolicy.yaml`)

## Running

```bash
# Locally (dev):
PYTHONPATH=../../packages:. python -m uvicorn app.main:app --port 8300

# Tests:
python -m pytest -q          # service smoke tests
# (the exhaustive threat-model suite lives in ../../security/tests)
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness + fixed advisory/read-only posture. |
| GET | `/capabilities` | Dashboard nav gating + safety posture. |
| POST | `/api/v1/ingest/uploads?parser=&filename=` | Upload raw file body; runs the full control pipeline. |
| GET | `/api/v1/ingest/uploads` | List the caller-tenant's uploads. |
| GET | `/api/v1/ingest/uploads/{id}` | Upload metadata (tenant-checked). |
| GET | `/api/v1/ingest/uploads/{id}/content` | Upload content (tenant-checked). |
| GET | `/api/v1/ingest/uploads/{id}/audit` | Hash-chained audit trail for the upload. |

The tenant is taken from the `X-Tenant-Id` header (a stand-in for the Keycloak
JWT tenant claim; wired to real identity in deployment).

## Platform independence

This service is **optional**: the platform is fully functional when it is
stopped. Nothing in `packages/` or the other services imports it (asserted by
`security/tests/test_platform_invariants.py`).
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
