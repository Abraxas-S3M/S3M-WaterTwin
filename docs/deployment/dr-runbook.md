# Disaster Recovery (DR) Runbook

This runbook is the **actionable drill** for recovering the S3M-WaterTwin
persistent store from a `pg_dump` backup and **proving the tamper-evident audit
chain is still intact after the restore**. It complements
[`backup-recovery.md`](backup-recovery.md) (which covers backup mechanics,
scheduling, and recovery objectives) with a repeatable, assertion-driven
procedure you can run as a scheduled game-day.

- **Scope:** the TimescaleDB/PostgreSQL database (`watertwin-timescaledb`,
  volume `timescale_data`) — the only stateful component. It holds the
  `telemetry` hypertable, the `telemetry_batch` ingest ledger, the append-only
  `audit_event` hash chain, and `recommendation` cards. Everything else is
  stateless and rebuilt from images.
- **Read-only posture:** backups and restores only ever contain advisory /
  synthetic artifacts. There is no control state and no control-write path
  anywhere in the platform.

## Recovery objectives

| Objective | Target | How it is met |
|-----------|--------|---------------|
| RPO (data loss) | ≤ 24h (nightly), tighter with PITR | Nightly `pg_dump` via `scripts/backup_audit_db.sh`; add WAL archiving/PITR for sub-daily RPO. |
| RTO (time to restore) | ≤ 1h | Single `pg_restore` into a rebuilt TimescaleDB container; services are stateless. |
| Integrity | Tamper-evident, verified | Append-only audit hash chain verified after every restore (this drill). |

## Automated drill (recommended)

Run the whole cycle — backup → restore into a **fresh** database → verify — with
a single script. It leaves the live database untouched (it restores into a
throwaway `watertwin_dr_restore` database) and asserts the recovered chain is
intact and identical to the live one.

```bash
# With the stack running (docker compose up -d):
scripts/dr_drill.sh
# or
make dr-drill
```

Expected tail on success:

```
[dr] PASS: restored audit chain verifies (ok=true)
[dr] PASS: event count preserved (<n>)
[dr] PASS: chain head hash identical after restore
[dr] DR DRILL PASSED: pg_dump/pg_restore recovered the database and the
[dr] tamper-evident audit chain is intact and identical post-restore.
```

The drill reuses:

- [`scripts/backup_audit_db.sh`](../../scripts/backup_audit_db.sh) — the same
  `pg_dump -Fc` backup used in production (with a SHA-256 sidecar it re-checks);
- [`scripts/verify_audit_chain.py`](../../scripts/verify_audit_chain.py) — the
  standalone, off-host chain verifier (used as a cross-check when the host has
  `psycopg`), which mirrors the service's `app/audit.py` algorithm.

What it asserts:

1. the restored chain verifies (`ok == true`);
2. the event **count** is preserved across the restore; and
3. the chain **head hash** is byte-for-byte identical to the live chain (proving
   no event was added, dropped, or altered by the backup/restore round-trip).

## Manual drill (step-by-step)

Use this when you need to restore for real, or to walk the procedure by hand.

### 1. Take (or locate) a verified backup

```bash
scripts/backup_audit_db.sh /var/backups/watertwin
sha256sum -c /var/backups/watertwin/watertwin-audit-<timestamp>.dump.sha256
```

### 2. Record the pre-incident chain state (if the DB is still readable)

```bash
curl -fsS http://localhost:8000/api/v1/audit/verify
# -> {"ok": true, "count": <n>, "head": "<hash>"}   (auditor/admin token if auth enforced)
```

Note the `count` and `head` — the restore must reproduce them exactly.

### 3. Restore

Restore into a fresh database (safe, non-destructive) …

```bash
docker exec watertwin-timescaledb \
  psql -U watertwin -d watertwin \
  -c "DROP DATABASE IF EXISTS watertwin_dr_restore WITH (FORCE);" \
  -c "CREATE DATABASE watertwin_dr_restore;"

docker cp watertwin-audit-<timestamp>.dump watertwin-timescaledb:/tmp/dr.dump
docker exec watertwin-timescaledb \
  pg_restore --no-owner --no-privileges -U watertwin -d watertwin_dr_restore /tmp/dr.dump
```

… or, to recover in place over the live database (destructive):

```bash
docker compose stop watertwin-api          # quiesce writers first
pg_restore --clean --if-exists --no-owner --no-privileges \
  --dbname='postgresql://watertwin:watertwin@localhost:5432/watertwin' \
  watertwin-audit-<timestamp>.dump
docker compose start watertwin-api
```

### 4. Verify audit-chain integrity post-restore

Because the dump captures the `prev_hash`/`hash` columns verbatim, a faithful
restore yields a chain that still verifies. Confirm it three independent ways:

```bash
# a) Standalone verifier straight against the restored database:
python scripts/verify_audit_chain.py \
  --database-url postgresql://watertwin:watertwin@localhost:5432/watertwin_dr_restore

# b) Off-host: verify a JSON export of the chain (e.g. archived with the dump):
python scripts/verify_audit_chain.py --json audit-export.json

# c) In place (after an in-place restore): the API endpoint
curl -fsS http://localhost:8000/api/v1/audit/verify
```

A healthy result is `{"ok": true, "count": <n>, "head": "<hash>"}` with `count`
and `head` matching what you recorded in step 2. If instead you get
`{"ok": false, "broken_at": "<event-id>", ...}`, the restored data was altered
relative to when it was written (or the dump was corrupted): **treat it as a
security event**, discard this dump, and restore from a known-good,
checksum-verified backup (prefer off-host WORM storage).

### 5. Clean up

```bash
docker exec watertwin-timescaledb \
  psql -U watertwin -d watertwin -c "DROP DATABASE IF EXISTS watertwin_dr_restore WITH (FORCE);"
```

## Related drills

- **Store-and-forward chaos drill** —
  [`tests/chaos/edge_gateway_chaos.sh`](../../tests/chaos/edge_gateway_chaos.sh)
  kills the edge-gateway mid-stream and proves ingestion recovers with no data
  loss, no duplication, and a still-valid audit chain.
- **Load / smoke** — [`tests/load/`](../../tests/load/) drives the ingest + read
  paths; the smoke profile runs in CI (non-blocking).

## Why the chain survives a restore

Every audit row stores the hash of the previous row (`prev_hash`) and its own
`hash = sha256(prev_hash + canonical(event_core))`. A logical `pg_dump`
preserves those columns exactly, and `seq` preserves append order, so
re-walking the restored chain reproduces every hash. Any post-restore
divergence — a dropped, reordered, added, or edited event — changes a hash and
is caught by the verifier. This is the same guarantee the append-only trigger
enforces on the live table, extended across the backup/restore boundary.
