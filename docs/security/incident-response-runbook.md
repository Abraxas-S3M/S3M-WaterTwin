# Incident Response Runbook

This runbook is the operational procedure for handling a suspected security
incident affecting WaterTwin. It follows the lifecycle
**detection → triage → containment → audit-export → recovery**, and it is written
for the platform's specific posture: WaterTwin is **advisory and read-only**, so
the goal of incident response is to protect **advisory integrity, the audit
trail, identities, and availability** — never to "regain control of the plant,"
because WaterTwin has no control-write path (see
[`control-boundaries.md`](./control-boundaries.md)).

> **Safety note before you start.** WaterTwin cannot actuate equipment. Even in a
> total compromise of the WaterTwin stack, plant control remains with the
> customer's separate, governed OT systems and qualified human operators. If a
> WaterTwin incident coincides with a real plant-safety concern, the plant's own
> OT incident procedures and human operators take precedence — do not wait on
> WaterTwin recovery to act on plant safety.

Use this alongside:
- [`threat-model.md`](./threat-model.md) — what can go wrong per boundary.
- [`iec62443-architecture.md`](./iec62443-architecture.md) — zones/conduits to
  isolate.
- [`../deployment/backup-recovery.md`](../deployment/backup-recovery.md) — the
  backup/restore procedure this runbook references for recovery and DR testing.

---

## 0. Roles

| Role | Responsibility |
|------|----------------|
| **Incident Commander (IC)** | Owns the incident, decisions, and comms; runs this runbook. |
| **Operator on shift** | Confirms plant-side status is unaffected; liaises with OT team. |
| **Platform/DevOps** | Executes containment, export, and recovery commands. |
| **Auditor** | Verifies the audit chain (`auditor`/`admin` role) before/after actions. |

Record a timestamped timeline from the first alert; every action below should be
logged with who/when.

---

## 1. Detection

Watch for these signals; any one is enough to open an incident.

| Signal | Where it shows up |
|--------|-------------------|
| **Audit chain broken** | `GET /api/v1/audit/verify` returns `{"ok": false, "broken_at": ...}` |
| **Auth anomalies** | Spikes in 401/403; logins from unexpected identities; `authentication DISABLED (dev bypass)` in production logs (must never appear) |
| **Cert/conduit failures** | TLS/mTLS validation failures on a conduit; unexpected cert expiry; OPC UA security downgraded to `None` |
| **Ingest anomalies** | `/health` shows an unexpected active source or unexpected fallback-to-synthetic; implausible telemetry / provenance mismatch |
| **Boundary regression** | CI safety-boundary guard trips (`control_write_enabled = True` detected) — treat any such build as an incident |
| **Egress anomaly** | Outbound connections from the IT zone to anything other than the allowlisted destinations (esp. unexpected S3M-Core / internet egress) |
| **Availability** | Health checks failing; service crash-loops; DB unreachable |
| **Supply chain** | `pip-audit` / `npm audit` / `gitleaks` gate failures on a merged change |

**On detection:** open the incident, assign an IC, start the timeline, and
snapshot current state (logs, `/health`, `audit/verify` output) **before**
changing anything.

---

## 2. Triage

Classify the incident so containment is proportionate.

1. **Confirm it's real.** Rule out benign causes (planned cert rotation, a
   known dev bypass in a non-prod env, a scheduled maintenance restart).
2. **Scope the boundary** using the [threat model](./threat-model.md):
   - **Ingest (B1)** — bad/spoofed telemetry, unexpected source/fallback.
   - **API (B2)** — auth/RBAC anomaly, DoS.
   - **LLM (B3)** — anomalous assistant output, unexpected S3M-Core egress.
   - **Audit (B4)** — broken chain / tamper indication.
3. **Confirm the safety invariant holds.** Verify every response still reports
   `control_write_enabled=false` and that no control-write path exists (the CI
   guard and code make this structural). Confirm with the operator that plant
   control is unaffected.
4. **Assign severity:**

| Severity | Criteria | Example |
|----------|----------|---------|
| **SEV-1** | Audit tamper confirmed, credential/cert compromise, or boundary regression | `audit/verify` broken; leaked key; `control_write_enabled=True` in a build |
| **SEV-2** | AuthN/AuthZ bypass risk, confirmed intrusion without audit tamper, unexpected egress | Forged-token attempts succeeding; rogue S3M-Core endpoint |
| **SEV-3** | Availability / degraded advice, no integrity or identity impact | DoS on the API; OT feed flapping to synthetic |

Escalate to the customer's OT/security contacts per SLA for SEV-1/SEV-2.

---

## 3. Containment

Contain by boundary, most-isolating action first. Prefer **fail-closed**: it is
acceptable for advice to be temporarily unavailable.

**Global (any SEV-1/SEV-2):**

- **Isolate the affected zone/conduit** per
  [`iec62443-architecture.md`](./iec62443-architecture.md): pull the IT-zone
  egress allowlist to deny-all except what recovery needs; block the suspect
  conduit at the firewall.
- **Rotate/revoke compromised credentials immediately** — revoke certs
  (CRL/OCSP or short TTL), disable the affected Keycloak client/user, rotate the
  DB role password, and disable the OT service account. Revocation fail-closes
  the corresponding conduit.

**By boundary:**

| Boundary | Containment action |
|----------|--------------------|
| **Ingest (B1)** | Force the source to synthetic (or stop the edge collector); block the suspect OT/edge source IP on C2/C3. Ingest is read-only, so OT cannot be reached to write regardless. |
| **API (B2)** | Ensure auth is **enforced** (`WATERTWIN_AUTH_DISABLED` must be `false`/unset in prod); revoke sessions by rotating Keycloak keys; put the API behind the edge rate-limiter/WAF or take `dashboard`/`watertwin-api` offline. |
| **LLM (B3)** | Unset `S3M_CORE_URL` to disable the quad-engine egress (the assistant continues via grounded local fallback, or disable the assistant endpoint). Block C7 egress. |
| **Audit (B4)** | **Do not** attempt to "fix" audit rows — the store is append-only by design. Stop the API to prevent further writes over a suspect DB, preserve the current volume, and proceed to export (§4) before any restore. |

**Do not destroy evidence.** Snapshot volumes/logs before restarting or
restoring. Preserve the exact `pg_dump` of the current (even if suspect) state
for forensics.

---

## 4. Audit-export

Before recovery, export the audit trail for forensics and to establish the
last-known-good point. The audit trail is the tamper-evident system of record.

1. **Verify the current chain state** (record the result, whatever it is):

   ```bash
   curl -fsS http://localhost:8000/api/v1/audit/verify
   # {"ok": true, "count": <n>, "head": "<hash>"}  OR  {"ok": false, "broken_at": "<event-id>", ...}
   ```

   (Requires an `auditor`/`admin` token when auth is enforced.)

2. **Export the audit events** for the incident window for offline analysis:

   ```bash
   # Read via the API (role-gated), narrowing with the same query params the API supports
   curl -fsS -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8000/api/v1/audit?limit=1000" > incident-audit-$(date -u +%Y%m%dT%H%M%SZ).json
   ```

3. **Take a forensic database export** (captures the `prev_hash`/`hash` columns
   verbatim so the chain is still verifiable from the dump) using the standard
   backup script:

   ```bash
   scripts/backup_audit_db.sh /var/backups/watertwin-incident
   # writes watertwin-audit-<UTC>.dump + .sha256
   ```

   See [`../deployment/backup-recovery.md`](../deployment/backup-recovery.md) for
   the full backup mechanics (custom-format `pg_dump -Fc`, checksums, off-host
   WORM storage).

4. **Copy exports off-host** to versioned, write-once (WORM) storage so the
   evidence itself cannot be altered.

5. **Interpret the chain:** a `broken_at` result means stored events were altered
   relative to when they were written (tampering or dump corruption) — this is a
   **SEV-1** finding and drives recovery from a known-good backup below.

---

## 5. Recovery

Restore service from a known-good state, then re-verify every invariant before
declaring the incident closed.

1. **Choose a known-good restore point.** Use the most recent checksum-verified
   backup taken *before* the compromise window. Verify integrity first:

   ```bash
   sha256sum -c watertwin-audit-<timestamp>.dump.sha256
   ```

2. **Restore** following
   [`../deployment/backup-recovery.md`](../deployment/backup-recovery.md)
   (stop the API, restore into a fresh DB with `pg_restore`, restart the stack):

   ```bash
   docker compose stop watertwin-api
   # restore per backup-recovery.md, then:
   docker compose up -d
   curl -fsS http://localhost:8000/health
   ```

3. **Re-verify the audit chain** on the restored data:

   ```bash
   curl -fsS http://localhost:8000/api/v1/audit/verify   # expect {"ok": true, ...}
   ```

   If it still reports `ok:false`, the chosen backup is not clean — step back to
   an earlier known-good backup.

4. **Re-establish trust material:** confirm rotated certs/keys are in place,
   revoked credentials stay revoked, auth is **enforced**, and egress/ingress
   allowlists are restored to default-deny.

5. **Confirm the safety boundary:** verify responses report
   `control_write_enabled=false`, the CI boundary guard passes, and the operator
   confirms plant control was never affected.

6. **Restore ingest deliberately:** bring the OT source back only after the C2/C3
   conduits and the read-only service account are confirmed clean; watch
   `/health` for the expected active source (no unexpected fallback).

7. **Backup-restore test reference.** Recovery must be exercised, not assumed.
   Periodically (and after any recovery) run the **backup-restore test** — restore
   a recent dump into a scratch database and confirm
   `GET /api/v1/audit/verify` returns `{"ok": true}` and health is green — per
   [`../deployment/backup-recovery.md`](../deployment/backup-recovery.md)
   (see its *Restore* and *Verify the audit chain after recovery* sections, and
   the RPO/RTO recovery objectives). A recovery path that has never been tested
   is not a recovery path.

---

## 6. Post-incident

- **Close the timeline** and write a blameless post-mortem: what happened, how it
  was detected, containment/recovery actions, and time-to-detect/-recover.
- **Track corrective actions**: e.g. tighten an allowlist, shorten cert TTLs, add
  an alert for the missed signal, or file a follow-up to remove a temporarily
  accepted advisory ([`accepted-advisories.md`](./accepted-advisories.md)).
- **Feed the threat model**: if a new threat or gap was found, update
  [`threat-model.md`](./threat-model.md).
- **Verify DR objectives** were met (RPO/RTO in
  [`../deployment/backup-recovery.md`](../deployment/backup-recovery.md)) and
  adjust backup frequency / WAL archiving if not.

---

## 7. Quick reference (checklist)

- [ ] **Detect** — capture `/health`, `audit/verify`, logs before touching anything.
- [ ] **Triage** — confirm real; scope boundary (B1–B4); confirm `control_write_enabled=false`; assign SEV.
- [ ] **Contain** — isolate zone/conduit; rotate/revoke credentials + certs; fail-closed.
- [ ] **Audit-export** — `audit/verify`, export events + `pg_dump` (checksummed) off-host to WORM.
- [ ] **Recover** — restore known-good backup; re-verify chain; re-enforce auth/allowlists; confirm boundary; run the backup-restore test.
- [ ] **Post-incident** — post-mortem, corrective actions, update threat model & DR objectives.

## References

- [`../deployment/backup-recovery.md`](../deployment/backup-recovery.md) —
  backup, restore, audit-chain verification, and RPO/RTO (recovery + backup-restore test).
- [`threat-model.md`](./threat-model.md) — per-boundary threats & residual risk.
- [`iec62443-architecture.md`](./iec62443-architecture.md) — zones/conduits to
  isolate; cert lifecycle.
- [`control-boundaries.md`](./control-boundaries.md) — the read-only safety
  boundary.
- [`identity.md`](./identity.md) — identity, RBAC, and the auth-enforced/dev-bypass modes.
- [`accepted-advisories.md`](./accepted-advisories.md) — accepting/tracking scan findings.
