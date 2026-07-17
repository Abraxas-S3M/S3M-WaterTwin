# WaterTwin Threat Model (STRIDE)

This is a **STRIDE-style threat model** for the WaterTwin platform. It analyzes
four trust boundaries — **ingest**, the **API**, the **LLM boundary**, and the
**audit trail** — and records the threats, existing mitigations, and residual
risk for each. It complements the network/zone view in
[`iec62443-architecture.md`](./iec62443-architecture.md), the application-level
guarantees in [`control-boundaries.md`](./control-boundaries.md), and the
identity model in [`identity.md`](./identity.md).

> **Overriding invariant.** WaterTwin is advisory and read-only: there is **no
> control-write path anywhere** in the platform (enforced in code and by the CI
> boundary guard). This constrains *impact* for the entire model — the worst
> realistic outcome of any threat below is **bad advice, denial of service, or a
> confidentiality/integrity issue on advisory data**, never direct actuation of
> plant equipment. The threat model is written to keep it that way.

STRIDE categories: **S**poofing, **T**ampering, **R**epudiation, **I**nformation
disclosure, **D**enial of service, **E**levation of privilege.

---

## 1. Assets and trust boundaries

**Assets worth protecting:**

- The **read-only boundary** itself (the guarantee of no control write).
- **Advisory integrity** — recommendations/briefs must be honest and grounded.
- The **tamper-evident audit trail** (append-only hash chain).
- **Telemetry & operational data** (synthetic today; potentially sensitive OT
  data in a real deployment).
- **Identities & credentials** (JWTs, DB roles, OT service accounts, certs).

**Trust boundaries (each analyzed below):**

| # | Boundary | Crossing | Primary concern |
|---|----------|----------|-----------------|
| B1 | **Ingest** | OT / edge → `watertwin-api` | Untrusted OT data entering; keeping ingest read-only |
| B2 | **API** | Operator browser → `watertwin-api` | AuthN/AuthZ; protecting the approval + read surface |
| B3 | **LLM boundary** | `watertwin-api` ↔ assistant / S3M-Core quad-engine | Ungrounded output; keeping the LLM away from DB & control |
| B4 | **Audit** | `watertwin-api` → `timescaledb` (`audit_event`) | Non-repudiation; tamper evidence |

---

## 2. Data-flow overview

```
 [OT source]--readonly-->[edge collector]--C3-->[watertwin-api]--+--> [timescaledb: telemetry/audit/reco]
                                                     |            |
 [operator browser]--OIDC JWT-->[dashboard]---C1-----+            +--> [hydraulic-sim / treatment-sim] (advisory)
                                                     |
                                                     +--(assembled advisory packet)--> [S3M-Core quad-engine] (optional)
                                                     |
                                                [assistant] -- grounded aggregation of platform outputs + docs
```

Note what is **absent**: there is no arrow from `watertwin-api`, the assistant,
or S3M-Core back toward OT. That missing arrow is the core safety property.

---

## 3. B1 — Ingest (OT / edge → API)

**Scope:** the read-only telemetry sources
(`services/watertwin-api/app/sources/` — synthetic, OPC UA, Modbus, historian),
tag normalization, and the C3 conduit into `watertwin-api`.

| STRIDE | Threat | Mitigation | Residual |
|--------|--------|------------|----------|
| **S** | A rogue host impersonates the OT source or edge collector to inject false telemetry | mTLS + source-IP allowlist on C2/C3; OPC UA `SignAndEncrypt`; canonical schema validation on ingest | Low — spoofed data is still advisory-only and provenance-tagged |
| **T** | Telemetry is manipulated in transit or malformed frames are injected | mTLS in transit; tag normalization validates/maps to the canonical model; provenance recorded per reading | Low–Med — bad input can skew *advice*, never control |
| **R** | Source of an ingested reading is later disputed | Every reading carries provenance (`synthetic` vs. real feed) and the active source is surfaced in `/health` | Low |
| **I** | Real OT data (potentially sensitive) is exposed to the IT zone or logs | Edge brokers/normalizes before IT sees it; least data forwarded; no raw OT frames stored | Med (deployment-dependent) — customer classifies OT data |
| **D** | A flooded/hung OT feed stalls or crashes ingest | `SourceUnavailable` handling → fail-safe fallback to synthetic; per-operation timeouts; service never crashes on a bad feed | Low |
| **E** | A compromised connector is used to write back to OT ("pivot to control") | **Structurally impossible:** the `TelemetrySource` interface has *no* write method; OPC UA uses `read_value` only, Modbus uses read-only function codes, historian uses `SELECT`/read only; read-only OT service account | Very low — no write path exists to escalate into |

**Key property:** ingest is read-only *by construction*, not by policy. The most
severe ingest attack yields **degraded advice**, contained by the read-only
boundary and provenance tagging.

---

## 4. B2 — API (operator browser → API)

**Scope:** `watertwin-api` (`/api/v1`), Keycloak-backed OIDC/JWT auth, RBAC, and
the dashboard.

| STRIDE | Threat | Mitigation | Residual |
|--------|--------|------------|----------|
| **S** | Attacker forges a token or replays one to act as an operator | JWT signature validation (RS256 via Keycloak JWKS), pinned issuer, expiry checks; optional audience check; tokens held **in memory only** (no `localStorage`/cookies) | Low |
| **T** | Request tampering to approve a recommendation the operator didn't intend | TLS on C1; server-side RBAC re-checks every request; approval only changes recommendation status, never equipment | Low |
| **R** | An operator denies having approved/rejected a recommendation | Approvals are RBAC-gated and written to the tamper-evident audit trail with actor identity | Low |
| **I** | API leaks secrets (model paths, credentials, connection strings) | By contract the API returns advisory outputs only; no secret/credential is surfaced; errors are sanitized | Low |
| **D** | Request flooding degrades the advisory service | Stateless services scale/restart (`restart: unless-stopped`); health checks; deploy a rate-limiter/WAF at the edge in production | Med — DoS affects availability of *advice*, not safety |
| **E** | An under-privileged user reaches a gated action (approve/reject, scenario, reset, audit read) | Server-side `require_role`: `operator`/`admin` for approvals, `engineer`/`admin` for scenario/reset, `auditor`/`admin` for audit read; 401 (no/invalid token) / 403 (under-privileged) | Low |

**Notes:**

- Auth is **enforced by default**; the `WATERTWIN_AUTH_DISABLED=true` bypass is
  an explicit, logged dev-only opt-out and never the production default (see
  [`identity.md`](./identity.md)).
- The highest-privilege *write* action any human has is **approving a
  recommendation** — which still does not touch equipment. There is no API-level
  escalation that reaches control.
- CORS is an allowlist (`WATERTWIN_CORS_ORIGINS`); set it to the dashboard origin
  in production.

---

## 5. B3 — LLM boundary (assistant / S3M-Core quad-engine)

**Scope:** the S3M Operations Assistant
(`services/watertwin-api/app/assistant.py`) and the optional S3M-Core quad-engine
connector (`app/s3m_connector.py`).

> **Explicit, load-bearing statement:** the LLM (the assistant / S3M-Core
> quad-engine reasoning layer) has **no database access and no control
> authority.** It is handed an *assembled advisory packet* built from
> already-computed platform outputs plus retrieved documents — never a database
> connection, a connection string, a credential, or any handle that could reach
> OT. Any action it "recommends" is emitted as a `pending` recommendation card
> that requires human operator approval, and there is no code path from the LLM
> to a control write. This is by design and is verified by the surrounding
> boundary tests.

| STRIDE | Threat | Mitigation | Residual |
|--------|--------|------------|----------|
| **S** | A spoofed/rogue S3M-Core endpoint returns malicious "orchestration" output | Connector is off unless `S3M_CORE_URL` is set; mTLS + egress allowlist (C7); the *answer text is assembled from local platform context regardless*, so a hostile endpoint cannot inject free-form content into the answer | Low |
| **T** | Prompt/data injection via operator question or a retrieved document steers the model | Deterministic intent classification; answers are **grounded** in platform layer outputs + named documents; the assistant *never answers from general model knowledge* — no-grounding → explicit "insufficient data" | Med — injection could bias phrasing, but recommendations remain `pending` + human-reviewed |
| **R** | An LLM-influenced recommendation is later disputed | Every answer records its `Evidence` (assets, documents, assumptions, timestamp) and any card is auditable; approval is a separate human, audited action | Low |
| **I** | The model exfiltrates secrets or DB contents | **No DB handle and no secrets are ever passed to the LLM;** only an advisory packet (already-computed outputs + doc refs). Nothing sensitive is in scope to leak | Very low |
| **D** | S3M-Core is slow/unreachable and stalls answers | Short client timeout (3s) + graceful `S3mCoreUnavailable` → grounded **local fallback** (`fallback_local`); the assistant still answers from platform data | Low |
| **E** | The LLM "decides" to take an action / escalate to control | **Impossible:** the LLM has no control conduit; output is a `pending` card requiring `operator`/`admin` approval; `control_write_enabled=false` on every response | Very low |

**Key property:** the LLM is a *reasoning aid over already-vetted data*, walled
off from the database and from control. Compromising it degrades **advice
quality**, not safety, and cannot reach OT or the datastore.

---

## 6. B4 — Audit (API → TimescaleDB)

**Scope:** the tamper-evident, append-only audit trail (`audit_event` in
`infrastructure/database/init.sql`) and `GET /api/v1/audit` / `audit/verify`.

| STRIDE | Threat | Mitigation | Residual |
|--------|--------|------------|----------|
| **S** | An unauthenticated caller reads or writes the audit trail | Audit **read** requires `auditor`/`admin`; audit **writes** happen only via the app role over TLS; JWT-authenticated | Low |
| **T** | An attacker edits/deletes audit rows to hide activity | **Append-only trigger** rejects `UPDATE`/`DELETE`; each row stores `prev_hash`+`hash` (SHA-256 chain) so any edit breaks the chain and all rows after it | Low — tampering is *detectable*, not merely discouraged |
| **R** | A user denies an approval/scenario/reset they performed | Every advisory action (scenario run, recommendation created/decided, report, reset) is appended with actor + timestamp | Low |
| **I** | Sensitive data leaks through audit payloads | Audit payloads record advisory actions/metadata, not secrets or model paths; read access is role-gated | Low |
| **D** | Audit writes are blocked, or the chain is truncated to cause loss | API degrades gracefully to in-memory when no DB is configured; nightly `pg_dump` + off-host WORM copies preserve history; `TRUNCATE` is a deliberate demo-reset convenience, not a row-level bypass | Med — availability/retention is deployment-dependent |
| **E** | The app DB role is abused to rewrite history | The DB role is **append-only** for `audit_event` (trigger-enforced); even a compromised app role cannot silently rewrite past events | Low |

**Verification & recovery:** after any restore, `GET /api/v1/audit/verify`
re-walks the chain (`{"ok": true, ...}` when intact; `broken_at` when altered).
A broken chain is treated as a **security event** (see the
[incident-response runbook](./incident-response-runbook.md) and
[`../deployment/backup-recovery.md`](../deployment/backup-recovery.md)).

---

## 7. Cross-cutting threats & controls

| Concern | Control |
|---------|---------|
| Transport security | mTLS on service-to-service conduits; TLS + JWT on the human conduit (see [`iec62443-architecture.md`](./iec62443-architecture.md) §9–10) |
| Credential hygiene | Read-only OT service accounts; append-only DB role; tokens in-memory; certs rotated/revoked; `gitleaks` secret-scan gate |
| Supply chain | CycloneDX SBOMs + `pip-audit` + `npm audit` gates; accepted advisories logged ([`accepted-advisories.md`](./accepted-advisories.md)) |
| Boundary regression | CI safety-boundary guard fails the build if `control_write_enabled = True` ever appears in `services/`/`packages/` |
| Network exposure | Default-deny ingress/egress allowlists; no general internet egress from the IT zone |

---

## 8. Residual risk summary

| Boundary | Highest residual | Bounded by |
|----------|------------------|------------|
| Ingest (B1) | Skewed advice from bad/spoofed telemetry | Read-only-by-construction ingest; provenance tagging; human review |
| API (B2) | Availability (DoS) of the advisory service | Statelessness/restart; edge rate-limiting; no safety impact |
| LLM (B3) | Injection biasing advisory phrasing | Grounding + `pending` cards + human approval; no DB/control reach |
| Audit (B4) | Retention/availability of history | Append-only chain + off-host WORM backups; tamper is detectable |

Across all four boundaries the impact ceiling is the same, by design: **degraded
advice, reduced availability, or a detectable data-integrity event — never
autonomous or unauthorized actuation of the physical plant.**

## References

- [`iec62443-architecture.md`](./iec62443-architecture.md) — zones, conduits,
  mTLS, allowlists.
- [`control-boundaries.md`](./control-boundaries.md) — advisory/read-only
  boundary.
- [`identity.md`](./identity.md) — identity + RBAC.
- [`incident-response-runbook.md`](./incident-response-runbook.md) — response
  procedure.
- [`../deployment/backup-recovery.md`](../deployment/backup-recovery.md) — audit
  durability and restore.
- [`../architecture/s3m-core-contract.md`](../architecture/s3m-core-contract.md)
  — the upstream contract the assistant/quad-engine follow.
