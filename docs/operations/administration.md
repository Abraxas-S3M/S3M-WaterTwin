# Administration: licensing, usage metering & support (Commercial Hardening)

WaterTwin ships an **Administration** surface for commercial operation:
licensing / entitlement feature-gating, usage metering with a billing export,
a signed-update channel, and in-app support bundles. All of it lives behind the
`admin` role and is exposed under `/api/v1/admin/*` and the dashboard's
**Administration** page.

> **Safety boundary is untouched.** None of these capabilities is a control
> path and none can relax the advisory / read-only invariant. Feature-gating
> only *hides advisory features by plan*; metering is advisory bookkeeping; the
> update channel only *verifies* (never applies) a signed manifest; support
> bundles are read-only, secret-redacted diagnostics. Every response still
> carries `control_write_enabled=false` and the CI boundary guard remains in
> force. See [`../security/control-boundaries.md`](../security/control-boundaries.md).

---

## 1. Licensing / entitlements (feature-gating by tenant / plan)

Entitlements decide **what advisory features a tenant's plan includes**. This is
a product-packaging concern, deliberately **orthogonal to authentication/RBAC**
(which decides *who* may act) and to the safety boundary (which is fixed).

Implementation: [`services/watertwin-api/app/licensing.py`](../../services/watertwin-api/app/licensing.py).

### Plans

| Plan | Features | Limits (facilities / assets / monthly ingest) |
| --- | --- | --- |
| `enterprise` *(default)* | all | unlimited |
| `professional` | all except `signed_updates` | 5 / 250 / 5,000,000 |
| `standard` | simulation, water quality, predictive maintenance, metering, support | 1 / 50 / 500,000 |
| `starter` | water quality, support | 1 / 10 / 50,000 |

A deployment with **no license configured runs as `enterprise`**, so nothing is
gated by accident (and the existing test-suites keep every feature).

### Feature keys

`simulation_center`, `water_quality`, `predictive_maintenance`,
`energy_optimization`, `resilience`, `executive_value`, `operations_assistant`,
`usage_metering`, `support_bundle`, `signed_updates`.

### The gate

Premium advisory endpoints depend on `require_feature(...)`. When the tenant's
plan does not include the feature the request is refused with **402 Payment
Required** and a clear message — never by relaxing any safety property. Gated
today: the energy, resilience, executive, operations-assistant, water-quality,
and equipment/predictive-maintenance layers.

### Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `WATERTWIN_PLAN` | Named plan | `enterprise` |
| `WATERTWIN_TENANT_ID` | Tenant identifier in usage/billing | `default` |
| `WATERTWIN_LICENSE` | JSON override `{"plan","features":[...],"limits":{...}}` | unset |

### Safety-invariant guarantee

`licensing.safety_invariant_intact()` asserts that the control boundary is a
fixed advisory default and that **no plan's feature set can imply a
control-write path**. It is surfaced on `GET /api/v1/admin/entitlements` as
`safety_invariant_intact` and covered by tests
(`tests/test_licensing.py`).

---

## 2. Usage metering & billing export

Metering tracks the billable dimensions of usage for the current calendar-month
period (UTC):

* **facilities** — distinct facility ids seen (e.g. on a scenario run),
* **assets** — distinct assets under management (equipment/membrane reads),
* **ingest volume** — telemetry readings brought in through the read-only
  ingestion path.

Implementation: [`services/watertwin-api/app/metering.py`](../../services/watertwin-api/app/metering.py).
Counting is thread-safe in-memory aggregation and is reset by the demo
`/api/v1/reset`. A production deployment would additionally flush period
snapshots to TimescaleDB; that persistence is out of scope for this reference.

### Endpoints (admin)

| Endpoint | Returns |
| --- | --- |
| `GET /api/v1/admin/metering/usage` | current-period counts |
| `GET /api/v1/admin/metering/billing-export` | metered quantities against plan limits |

Exceeding a plan limit is a **billing signal only** (`within_limit=false`); it
never changes any safety property or blocks advisory reads.

---

## 3. Signed-update channel

See [`signed-updates.md`](./signed-updates.md). In short: **verify the Ed25519
signature before applying**, and **never auto-update in production** — the
service only reports channel status and verifies a supplied manifest; it has no
code path that downloads or applies an update.

---

## 4. Support bundles

An administrator can generate a support bundle — a single ZIP packaging recent
logs, the SBOMs, and a configuration snapshot, plus health / entitlement /
audit-tail snapshots — via `POST /api/v1/admin/support/bundle` or the dashboard
button.

Implementation: [`services/watertwin-api/app/support.py`](../../services/watertwin-api/app/support.py).

### Redaction (secrets never leave the platform)

Redaction is defence-in-depth:

1. Environment variables whose **name** looks like a secret (`*_TOKEN`,
   `*_SECRET`, `*PASSWORD*`, `*_DSN`, …) have their value masked.
2. Credentials embedded in **values** (e.g. the password in a
   `postgresql://user:pass@host` URL) are stripped, preserving the non-secret
   user/host for triage.
3. Every secret literal discovered above is additionally scrubbed from all
   free text (logs, audit payloads) — so a secret that leaked into a log line
   is removed too.

The bundle carries only advisory diagnostics and no control state. Redaction is
asserted by `tests/test_support_bundle.py` (no seeded secret appears anywhere in
the archive).

---

## RBAC

Every `/api/v1/admin/*` endpoint requires the `admin` role (401 unauthenticated,
403 under-privileged), consistent with the RBAC matrix in
[`../security/identity.md`](../security/identity.md). The dashboard hides the
Administration nav entry for non-admins.
