# watertwin-ingest

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
