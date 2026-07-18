# watertwin-ingest — data residency, retention & deletion

This document describes how uploaded content is **located** (data residency),
how long it is **kept** (retention), and exactly **what survives deletion**. It
covers regulated jurisdictions, with specific attention to **Saudi critical-
infrastructure** requirements.

Controls of record: `services/watertwin-ingest/app/residency.py`,
`app/retention.py`, `app/service.py`. Tests: `security/tests/test_retention_residency.py`.

## Data residency (where content is stored)

Each tenant carries a **residency region**. The ingest service refuses to place a
tenant's content outside its declared region (`ResidencyViolation`). The region
is configured per tenant; the platform default is set by
`INGEST_DEFAULT_RESIDENCY_REGION` (default `SA`).

### How storage location is configured per tenant

1. **Per-tenant policy.** Register a `ResidencyPolicy(tenant_id, region,
   enforced=True)`. When `enforced` is true (the default for regulated tenants),
   any attempt to store content in a different region fails closed.
2. **Region → storage backend.** Each region maps to a storage backend that
   physically resides in that jurisdiction (e.g. an in-country object store or a
   region-pinned volume). The chosen backend's region is passed to the ingest
   pipeline (`storage_region`) and checked against the tenant policy on every
   upload before any bytes are written.
3. **Default.** A tenant with no explicit policy inherits the platform default
   region and is treated as enforced.

### Saudi critical-infrastructure requirements

For Saudi critical-infrastructure operators, data localisation and sovereignty
are mandatory (National Cybersecurity Authority — NCA — Essential Cybersecurity
Controls / Critical Systems Cybersecurity Controls; SAMA and PDPL data-
localisation expectations). For these tenants:

- Set the residency region to `SA` and `enforced=True` (this is the platform
  default). The service will refuse to store their content anywhere but an
  in-Kingdom backend.
- Deploy the ingest service and its storage backend **inside the Kingdom** (an
  in-country region / on-prem). The deny-all egress policy
  ([`ingest-network-policy.md`](./ingest-network-policy.md)) additionally prevents
  content from leaving via the network: the only egress targets are the S3M and
  `watertwin-api` endpoints, which must themselves be in-region for a Saudi CI
  deployment.
- Keep the tamper-evident audit trail in-region as well; it contains metadata and
  hashes only (never file content), but is still treated as regulated data.

The combination — enforced `SA` residency + in-region storage backend +
deny-all egress + in-region S3M/API endpoints — keeps regulated content within
the jurisdiction end to end.

## Retention (how long content is kept)

Retention is configured per tenant (`RetentionPolicy`), defaulting to
`INGEST_DEFAULT_RETENTION_DAYS` (90 days) for content. A retention sweep
(`IngestService.sweep_retention`) deletes content that has aged past a tenant's
`content_retention_days`. Audit entries have their own, longer retention
(`audit_retention_days`, default 10 years) to satisfy regulatory record-keeping.

## Deletion behaviour — what survives and what does not

Deletion happens either on explicit request or via the retention sweep. In both
cases:

- **Does NOT survive deletion:** the uploaded **file content** and any derived
  parsed artifacts. The bytes are removed and the tenant's storage quota is
  returned. A subsequent content read returns `UploadNotFound`.
- **Survives deletion:** the tamper-evident **audit entries** — `upload.received`,
  `upload.scanned`, `upload.parsed`, `upload.approval`, and the `upload.deleted`
  event itself — together with their hash chain and the deleted content's
  SHA-256. These records contain **metadata and hashes only, never file content**,
  and are retained for the audit-retention period so that who-did-what remains
  non-repudiable after the content itself is gone.

This split is deliberate and tested: `test_retention_sweep_deletes_content_but_
keeps_audit` and `test_content_deletion_leaves_audit_intact` prove that content
is destroyed while the audit chain still verifies.
