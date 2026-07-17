# IEC 62443 Reference Architecture (Zones & Conduits)

This document describes the WaterTwin deployment architecture in the vocabulary
of **IEC 62443** — *zones*, *conduits*, and defense-in-depth — and shows how the
platform's **advisory, read-only** posture is enforced at the network layer, not
just in application code. It complements the application-level guarantees in
[`control-boundaries.md`](./control-boundaries.md) and the identity/RBAC design
in [`identity.md`](./identity.md), and it maps the deployment onto the
**XiiD-ready topology from B2** (see [§9](#9-mapping-to-the-xiid-ready-topology-from-b2)).

> **First principle.** WaterTwin is a *conductor*, not the physics engine, and it
> never writes to plant control (see
> [ADR-0001](../adr/ADR-0001-conductor-not-physics.md)). IEC 62443 gives us the
> vocabulary to prove that the *only* data path that crosses the OT/IT boundary
> is **read-only telemetry inbound**, and that no conduit carries a command back
> toward the process. Every response still reports `control_write_enabled=false`.

---

## 1. Purpose and scope

- **In scope:** the network segmentation model (zones/conduits), OT/IT
  separation, the edge DMZ, service-account and credential model, transport
  security (mTLS) and certificate lifecycle, and egress/ingress allowlists for
  the WaterTwin services defined in `docker-compose.yml`
  (`watertwin-api`, `dashboard`, `timescaledb`, `hydraulic-sim`,
  `treatment-sim`, `keycloak`) and the read-only OT connectors
  (`services/watertwin-api/app/sources/`).
- **Out of scope:** the customer's own OT security program (their SCADA/PLC
  hardening, physical security, and safety-instrumented systems). WaterTwin
  consumes from the OT environment across a read-only boundary; it does not
  manage it.

WaterTwin is a **SuC** (System under Consideration, in 62443 terms) that sits at
the *IT / enterprise* side of the boundary and reads from — but never controls —
the OT environment.

---

## 2. Reference model: Purdue levels and 62443 zones

WaterTwin aligns to the Purdue Enterprise Reference Architecture and the IEC
62443 zone model. The critical boundary is the **industrial DMZ (iDMZ)** between
the OT cell/site zones and the IT/enterprise zone.

```
 Level 5/4  ENTERPRISE / IT ZONE                     (WaterTwin runs here)
            +------------------------------------------------------------+
            |  dashboard (nginx)   watertwin-api   keycloak (OIDC/JWT)   |
            |  timescaledb (audit) hydraulic-sim   treatment-sim         |
            +------------------------------------------------------------+
                         ^  (read-only telemetry, canonical model)
                         |  CONDUIT C3  (mTLS, allowlisted)
 Level 3.5  EDGE / INDUSTRIAL DMZ (iDMZ)
            +------------------------------------------------------------+
            |  read-only OT connector / edge collector                   |
            |  (OPC UA client-read, Modbus read FCs, historian SELECT)   |
            +------------------------------------------------------------+
                         ^  (read-only pull only; no writeback)
                         |  CONDUIT C2  (mTLS / read-only service acct)
 Level 3    SITE OPERATIONS ZONE      historian, OT data aggregation
 Level 2    SUPERVISORY ZONE          SCADA / HMI
 Level 1    CONTROL ZONE              PLC / RTU / controllers
 Level 0    PROCESS ZONE             sensors & actuators (pumps, valves, dosing)
            +------------------------------------------------------------+
            |  CUSTOMER OT — WaterTwin NEVER writes to any of this        |
            +------------------------------------------------------------+
```

The arrows point **only upward** (toward IT). There is deliberately **no
downward conduit** from WaterTwin toward Levels 0–3: the platform has no code
path that writes to a control system (enforced in code and by the CI boundary
guard; see [`control-boundaries.md`](./control-boundaries.md)).

---

## 3. Zone definitions

| Zone | Purdue level | Members | Trust | WaterTwin role |
|------|--------------|---------|-------|----------------|
| **Process / Control / Supervisory** | 0–2 | Sensors, pumps, valves, dosing, PLC/RTU, SCADA/HMI | Highest safety criticality; customer-owned | **None.** Never read or written directly. |
| **Site Operations (OT)** | 3 | Plant historian, OT data aggregation, engineering workstations | OT-managed | Source of read-only telemetry (pull only). |
| **Edge / Industrial DMZ (iDMZ)** | 3.5 | Read-only OT connector / edge collector, tag-normalization | Brokered boundary | Terminates the OT-side conduit; forwards **canonical, read-only** telemetry up. |
| **Enterprise / IT** | 4–5 | `watertwin-api`, `dashboard`, `timescaledb`, `hydraulic-sim`, `treatment-sim`, `keycloak` | Application zone | Advisory orchestration, audit, operator UI. |
| **External advisory (optional)** | — | S3M-Core quad-engine (`S3M_CORE_URL`) | Untrusted-by-default; off by default | Receives an assembled advisory packet; **no DB or OT access**. |

Each zone has a defined **target security level (SL-T)**. The OT zones inherit
the customer's SL-T; WaterTwin's IT zone targets **SL 2** (protection against
intentional misuse by simple means) as a baseline, with SL 3 achievable when the
transport, identity, and allowlist controls in this document are all enabled.

---

## 4. Conduit definitions

A *conduit* is a controlled communication path between zones. Every WaterTwin
conduit is enumerated, authenticated, encrypted, and default-deny.

| ID | From → To | Payload | Direction | Controls |
|----|-----------|---------|-----------|----------|
| **C1** | Operator browser → `dashboard` / `watertwin-api` | HTTPS + OIDC bearer JWT | Request/response | TLS, Keycloak JWT (RS256/JWKS), RBAC, CORS allowlist |
| **C2** | Edge collector → OT source (historian / OPC UA / Modbus) | Read-only pull | **OT → edge only** | Read-only service account; mTLS or protocol auth; read function codes / `read_value` / `SELECT` only |
| **C3** | Edge collector → `watertwin-api` | Canonical telemetry (read-only) | **Edge → IT only** | mTLS, allowlisted source IP, schema-validated ingest |
| **C4** | `watertwin-api` → `timescaledb` | Telemetry, audit, recommendation writes | IT-internal | mTLS/TLS to Postgres, least-privilege DB role |
| **C5** | `watertwin-api` → `hydraulic-sim` / `treatment-sim` | Advisory what-if requests | IT-internal | mTLS, allowlisted; simulators are read-only advisory |
| **C6** | `watertwin-api` → `keycloak` (JWKS) | Public-key fetch for JWT validation | IT-internal | TLS, pinned issuer |
| **C7** | `watertwin-api` → S3M-Core quad-engine (optional) | Advisory packet (no secrets, no DB handle) | IT → external | mTLS, egress allowlist, disabled unless `S3M_CORE_URL` set |

**There is no conduit in the reverse (downward) direction toward OT.** C2 and C3
are physically one-directional in intent: the edge collector *pulls* from OT and
*pushes* canonical telemetry to IT; nothing flows back toward the process.

---

## 5. OT / IT separation

The OT/IT boundary is the single most important control in this architecture.

- **No direct OT reachability from IT.** `watertwin-api` never opens a socket to
  a PLC, SCADA server, or the process network. All OT data arrives *pre-brokered*
  through the edge collector across conduit C3.
- **Read-only by construction at every OT-touching layer.** The telemetry source
  abstraction (`services/watertwin-api/app/sources/base.py`) only defines a
  `read_latest()` method — there is no write method anywhere in the interface.
  Concrete connectors are read-only:
  - **OPC UA** (`sources/opcua.py`) connects as a *client* and calls
    `node.read_value()` only; it never calls a write/attribute-set method and
    never mutates the server address space.
  - **Modbus** (`sources/modbus.py`) uses **read-only function codes** only
    (read coils / discrete inputs / holding / input registers) — no write-coil
    or write-register calls.
  - **Historian** (`sources/historian.py`) uses a read-only `SELECT` (SQL), a
    read REST endpoint, or a CSV pull — never an `INSERT`/`UPDATE`.
- **Fail-safe fallback.** If a configured OT source is unreachable, the service
  logs and falls back to the built-in synthetic source rather than crashing
  (`SourceUnavailable` handling), and surfaces the active source + fallback state
  in `/health`. A degraded OT link therefore *never* creates pressure to relax
  the boundary.
- **Provenance is preserved across the boundary.** Every reading is tagged with
  its provenance (`synthetic` vs. a real OT feed) so a synthetic value can never
  be mistaken for validated plant data.

---

## 6. Edge DMZ (iDMZ)

The edge / industrial DMZ is the brokered boundary where the read-only collector
lives. Its job is to be the *only* thing that talks to OT, so the IT zone never
does.

- **Broker, don't bridge.** The collector terminates the OT-side conduit (C2)
  and originates a fresh IT-side conduit (C3). There is no transparent L2/L3
  bridge between OT and IT; traffic is proxied at the application layer.
- **Read-only service identity.** The collector authenticates to OT sources with
  a **read-only service account** (see [§7](#7-read-only-service-accounts)) whose
  privileges cannot write, even if the collector were compromised.
- **Tag normalization at the edge.** Raw OT tags are normalized to the canonical
  model (`app/tag_normalization.py`) at/above the DMZ, so the IT zone only ever
  sees a validated, schema-checked canonical payload — never raw, untrusted OT
  frames.
- **Minimal attack surface.** The collector exposes no inbound service to OT
  (it only *pulls*), and exposes only the single allowlisted C3 egress to
  `watertwin-api`.
- **Deployment note.** In the reference `docker-compose.yml` (single-host demo),
  the OT-source logic runs in-process inside `watertwin-api` for simplicity. In a
  production/segmented deployment the collector is deployed as a **separate edge
  node in the iDMZ**, and only conduit C3 crosses into the IT zone. The code is
  written so this split requires configuration, not re-architecture (the source
  is a pluggable, read-only seam).

---

## 7. Read-only service accounts

Every non-human identity is least-privilege and, wherever it touches OT or the
audit store, **read-only or append-only**.

| Account | Used by | Privilege | Rationale |
|---------|---------|-----------|-----------|
| OT source account | Edge collector → OT | **Read-only** (OPC UA browse/read, Modbus read FCs, historian `SELECT`) | Cannot write to the process even if the collector is compromised. |
| DB app role (`watertwin`) | `watertwin-api` → `timescaledb` | `INSERT`/`SELECT` on app tables; **append-only** on `audit_event` (UPDATE/DELETE rejected by trigger) | Enforces the tamper-evident audit chain at the storage layer. |
| Simulator client | `watertwin-api` → sims | Invoke advisory what-if endpoints only | Simulators are read-only; no state is controlled. |
| Keycloak client (`watertwin-dashboard`) | Dashboard | Public OIDC client (PKCE), no client secret | Browser cannot hold a confidential secret; tokens are in-memory only. |
| S3M-Core client (optional) | `watertwin-api` → quad-engine | Submit advisory packet; read structured result | The LLM/quad-engine has **no DB handle and no OT reachability** (see [§8](#8-the-llm--advisory-boundary)). |

**Principles enforced:**

- No account has a write path to OT. There is no "write" service account,
  because there is no write conduit.
- The audit DB role is *append-only* for `audit_event` — the append-only trigger
  in `infrastructure/database/init.sql` rejects `UPDATE`/`DELETE`, so even a
  compromised app role cannot silently rewrite history.
- Human write actions are limited to **operator approvals** (RBAC-gated, roles
  `operator`/`admin`), which change a recommendation's status only — never
  equipment (see [`identity.md`](./identity.md)).

---

## 8. The LLM / advisory boundary

The S3M Operations Assistant (`services/watertwin-api/app/assistant.py`) and the
optional S3M-Core quad-engine connector (`app/s3m_connector.py`) are treated as
an untrusted reasoning layer with a hard boundary:

- **No database access.** The LLM/quad-engine receives an *assembled advisory
  packet* (`WaterTwinPacket`) built from already-computed layer outputs plus
  retrieved documents. It is never handed a DB connection, connection string, or
  credential.
- **No control authority.** Any recommended action is emitted as a `pending`
  recommendation card requiring operator approval; there is no path from the LLM
  to a control write.
- **Grounded only.** The assistant never answers from general model knowledge —
  a question with no grounding data returns an explicit "insufficient data"
  answer. Every answer names the exact evidence used.
- **Off by default / egress-controlled.** The quad-engine connector is disabled
  unless `S3M_CORE_URL` is set; when enabled it is an allowlisted egress
  (conduit C7) and carries no secrets.

This boundary is analyzed in detail in the [threat model](./threat-model.md).

---

## 9. Transport security (mTLS)

All conduits carry authenticated, encrypted transport. **Mutual TLS** is the
target for every service-to-service conduit; TLS + bearer JWT secures the
human-facing conduit.

| Conduit | Transport | Client auth | Server auth |
|---------|-----------|-------------|-------------|
| C1 (browser → API/UI) | TLS 1.2+ | OIDC bearer JWT | Server cert |
| C2 (edge → OT) | mTLS or protocol-native (OPC UA `SignAndEncrypt`) | Read-only client cert / OT credential | OT server cert |
| C3 (edge → API) | mTLS | Edge client cert | API server cert |
| C4 (API → Postgres) | TLS (`sslmode=verify-full`), mTLS where supported | DB client cert / password over TLS | DB server cert |
| C5 (API → sims) | mTLS | API client cert | Sim server cert |
| C6 (API → Keycloak JWKS) | TLS, pinned issuer | — | Keycloak server cert |
| C7 (API → S3M-Core) | mTLS | API client cert | S3M-Core server cert |

mTLS requirements:

- **TLS 1.2 minimum, TLS 1.3 preferred**; modern cipher suites only.
- **Server certificate verification is mandatory** on every client
  (no `verify=false`). For Postgres, use `sslmode=verify-full`.
- **OPC UA** connections use the `SignAndEncrypt` security mode with an
  application certificate; anonymous/None security is not permitted for real OT
  feeds.
- Certificates chain to an internal CA (or the customer's PKI); public-internet
  CAs are only used for the operator-facing edge if it is internet-exposed.

---

## 10. Certificate lifecycle

Certificates and keys follow a defined lifecycle so that expiry or compromise is
a routine, non-disruptive event.

1. **Issuance.** Server/client certs are issued from an internal CA (or the
   customer PKI). Key pairs are generated on the target host; **private keys
   never leave the host** and are never committed to the repository.
2. **Storage.** Private keys live in a secrets manager / mounted secret with
   filesystem permissions restricted to the service user — never in images, env
   files committed to git, or the audit trail. The secret-scan gate
   (`gitleaks`) guards against accidental commits (see
   [`accepted-advisories.md`](./accepted-advisories.md)).
3. **Rotation.** Service certs are rotated on a fixed schedule (e.g. ≤ 90 days
   for leaf certs) and always **before** expiry. Rotation is staggered so no two
   ends of a conduit expire simultaneously. Short-lived certs are preferred where
   automation (e.g. cert-manager / SPIFFE-style issuance) is available.
4. **Revocation.** Compromised or decommissioned certs are revoked (CRL/OCSP or
   short TTL) and the corresponding service account is disabled. A revoked edge
   or OT cert immediately severs the read-only conduit — fail-closed.
5. **Monitoring.** Certificate expiry is monitored and alerted ahead of time; an
   expiring cert is treated as an operational (not emergency) task.
6. **Audit.** Issuance/rotation/revocation events are recorded in the operator's
   change management, and any cert-validation failure at a conduit is a security
   signal (see the [incident-response runbook](./incident-response-runbook.md)).

---

## 11. Network allowlists (ingress & egress)

The network is **default-deny**. Only the enumerated conduits above are
permitted; everything else is dropped.

**Ingress (what may reach each service):**

| Service | Allowed source | Port |
|---------|----------------|------|
| `dashboard` | Operator networks / reverse proxy | 443 (→ 80 internal) |
| `watertwin-api` | `dashboard`, edge collector (C3) | 8000 |
| `timescaledb` | `watertwin-api` only | 5432 |
| `hydraulic-sim` / `treatment-sim` | `watertwin-api` only | 8100 / 8080 |
| `keycloak` | Operator browser (login), `watertwin-api` (JWKS) | 8180 / 8080 |

**Egress (what each service may call out to):**

| Service | Allowed destination |
|---------|---------------------|
| Edge collector | The configured OT source(s) only (C2); `watertwin-api` (C3) |
| `watertwin-api` | `timescaledb`, `hydraulic-sim`, `treatment-sim`, `keycloak`, and — **only if `S3M_CORE_URL` is set** — the S3M-Core endpoint (C7) |
| `hydraulic-sim` / `treatment-sim` | None (no external egress required) |
| `dashboard` | `watertwin-api`, `keycloak` (browser-side) |

Allowlist principles:

- **No general internet egress** from the IT zone by default; the only optional
  outbound is the allowlisted S3M-Core conduit.
- **CORS is an application-layer allowlist** on `watertwin-api`
  (`WATERTWIN_CORS_ORIGINS`); set it to the dashboard origin in production
  (the `*` default is for local dev only).
- **OT is never an egress destination for the IT zone** — only the edge
  collector may reach OT, and only read-only.

---

## 12. Mapping to the XiiD-ready topology from B2

The **B2** design package defines the target **XiiD-ready** topology — an
identity-first segmentation where every zone crossing is authenticated by a
strong, centrally-governed identity fabric (XiiD) rather than by network
location alone. This section maps the B2 topology onto the concrete WaterTwin
architecture above.

| B2 / XiiD-ready concept | WaterTwin realization today | Notes |
|-------------------------|-----------------------------|-------|
| Identity fabric (XiiD) as the trust anchor | Keycloak OIDC/JWT issuer (`identity.md`) | Keycloak is the current, standards-based (OIDC/RS256) stand-in for the XiiD fabric; issuer/JWKS are pinned. |
| Per-crossing authentication (zero implicit trust) | Every conduit authenticated (JWT for C1; mTLS for C2–C7) | No conduit trusts network position alone. |
| OT/IT separation with a brokered edge | iDMZ edge collector (C2/C3), read-only | Matches the B2 edge-DMZ tier. |
| Least-privilege machine identities | Read-only OT service accounts; append-only DB role | See [§7](#7-read-only-service-accounts). |
| Governed credential lifecycle | Cert lifecycle ([§10](#10-certificate-lifecycle)); tokens in-memory only | XiiD-ready: identities are issued, rotated, and revoked centrally. |
| Advisory-only reasoning tier | LLM/quad-engine with no DB/OT access | See [§8](#8-the-llm--advisory-boundary). |
| Auditable, non-repudiable crossings | Tamper-evident append-only audit chain | Identity flows into the audit trail; `GET /api/v1/audit/verify`. |

**XiiD-readiness gaps (documented, not yet built):** federating Keycloak to the
XiiD identity fabric, issuing SPIFFE/SVID-style workload identities for C2–C7
mTLS, and centralizing certificate issuance/rotation under XiiD governance. These
are configuration/integration items on top of the existing seams — they do not
require relaxing the read-only boundary.

---

## 13. What this architecture does NOT change

- **No control write.** Segmentation, mTLS, and identity harden *who and what*
  may read; they never introduce a path that commands a PLC/SCADA/VFD/valve/
  pump/dosing system. Every response still reports `control_write_enabled=false`.
- **No weakened safety boundary.** The IEC 62443 controls are additive to — not a
  substitute for — the application-level guarantees in
  [`control-boundaries.md`](./control-boundaries.md) and the CI boundary guard.
- **No new dependencies.** This is an architecture/reference document; it
  introduces no code and no packages.

## References

- [`control-boundaries.md`](./control-boundaries.md) — application-level
  advisory/read-only boundary.
- [`identity.md`](./identity.md) — identity + RBAC (Keycloak/OIDC).
- [`threat-model.md`](./threat-model.md) — STRIDE threat model for the same
  components.
- [`incident-response-runbook.md`](./incident-response-runbook.md) — detection →
  recovery, including cert/conduit failure handling.
- [ADR-0001](../adr/ADR-0001-conductor-not-physics.md) — conductor, not physics.
- [`../deployment/backup-recovery.md`](../deployment/backup-recovery.md) — audit
  durability and restore.
