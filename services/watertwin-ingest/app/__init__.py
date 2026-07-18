"""watertwin-ingest service.

Customer-document ingestion for the S3M-WaterTwin Operations Assistant. This
service performs **text extraction only** from operator-supplied O&M manuals,
SOPs and design-basis documents so the Assistant can ground its answers in the
customer's own documents alongside the platform-seeded corpus.

It is deliberately narrow and defensive:

* It reads a document's *text layer* only. It never executes JavaScript, never
  extracts embedded files, never evaluates form fields, and never runs macros.
* Macro-enabled Office formats (``.docm``) are rejected outright.
* Scanned / image-only PDFs (no recoverable text layer) are reported as
  ``unparsed`` with a clear reason -- no OCR is performed in this service.
* Malformed input is reported as ``parse_failed`` -- it never crashes or hangs.

Extracted text is chunked with stable, deterministic boundaries. Every chunk
carries its source document id, page or section, and character offsets so a
downstream citation can point at a real location in a real file.
"""
