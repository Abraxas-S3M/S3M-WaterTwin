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
