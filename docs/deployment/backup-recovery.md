# Backup & Disaster Recovery

This document describes how to back up and restore the S3M-WaterTwin persistent
store and how the tamper-evident audit trail survives a recovery.

## What is persisted

The only stateful component is the **TimescaleDB / PostgreSQL 16** database
(`timescaledb` service in `docker-compose.yml`, container
`watertwin-timescaledb`, volume `timescale_data`). It holds:

| Object | Contents | Notes |
|--------|----------|-------|
| `telemetry` (hypertable) | Synthetic/simulated readings | Provenance always recorded; never measured plant data. |
| `audit_event` | Tamper-evident, append-only audit hash chain | Each row stores `prev_hash` + `hash`; append-only trigger rejects UPDATE/DELETE. |
| `recommendation` | Advisory recommendation cards + approval status | Advisory only; never a control-write path. |

Everything else (services, dashboard) is stateless and rebuilt from images. The
`watertwin-api` recommendation JSON cache is a convenience mirror; the database
is the source of truth. When no database is configured the API runs fully in
memory (`db_connected == false`) and there is nothing to back up.

There is **no control state and no control-write path** anywhere in the
platform, so backups only ever contain advisory / simulated artifacts.

## Backups (pg_dump)

Use the provided script, which writes a compressed custom-format archive
(`pg_dump -Fc`) plus a SHA-256 checksum:

```bash
# Default: connect with docker-compose credentials, write to ./backups
scripts/backup_audit_db.sh

# Or via make
make backup

# Custom output directory
scripts/backup_audit_db.sh /var/backups/watertwin

# Against a remote/managed database
WATERTWIN_DATABASE_URL='postgresql://user:pass@host:5432/watertwin' \
  scripts/backup_audit_db.sh /var/backups/watertwin
```

The script:

- resolves the connection from `WATERTWIN_DATABASE_URL` (preferred) or the
  discrete `PG*` variables;
- runs `pg_dump` locally, or transparently falls back to `docker exec` inside
  the `watertwin-timescaledb` container when no local `pg_dump` is installed;
- writes `watertwin-audit-<UTC-timestamp>.dump` and a `.sha256` sidecar;
- prunes dumps older than `BACKUP_RETENTION_DAYS` (default 30; set `0` to keep
  all).

Because the dump captures the audit `prev_hash`/`hash` columns verbatim, a
restored database yields a chain that still verifies (see below).

### Scheduling

Run it from cron (or a Kubernetes CronJob) on the DB host, e.g. nightly:

```cron
# /etc/cron.d/watertwin-backup — 02:15 UTC daily, keep 30 days
15 2 * * *  deploy  BACKUP_DIR=/var/backups/watertwin BACKUP_RETENTION_DAYS=30 \
  /opt/s3m-watertwin/scripts/backup_audit_db.sh >> /var/log/watertwin-backup.log 2>&1
```

Copy the resulting dumps and their `.sha256` files to off-host, versioned object
storage (e.g. S3 with object-lock/WORM) so the audit trail's tamper-evidence is
preserved end-to-end.

## Restore

1. Verify the dump integrity before restoring:

   ```bash
   sha256sum -c watertwin-audit-<timestamp>.dump.sha256
   ```

2. Stop the API so nothing writes during the restore:

   ```bash
   docker compose stop watertwin-api
   ```

3. Restore into a fresh database (custom-format dumps use `pg_restore`):

   ```bash
   # Recreate a clean database, then restore.
   docker exec -it watertwin-timescaledb \
     psql -U watertwin -c "DROP DATABASE IF EXISTS watertwin_restore;" \
                        -c "CREATE DATABASE watertwin_restore;"

   pg_restore --no-owner --no-privileges \
     --dbname='postgresql://watertwin:watertwin@localhost:5432/watertwin_restore' \
     watertwin-audit-<timestamp>.dump
   ```

   To restore in place over the existing database, use
   `pg_restore --clean --if-exists --dbname=<watertwin URI> <dump>`.

4. Restart the stack and confirm health:

   ```bash
   docker compose up -d
   curl -fsS http://localhost:8000/health
   ```

## Verify the audit chain after recovery

The audit trail is tamper-evident. After any restore, confirm the hash chain is
intact (auditor/admin token required when auth is enforced):

```bash
curl -fsS http://localhost:8000/api/v1/audit/verify
# -> {"ok": true, "count": <n>, "head": "<hash>"}
```

If the response is `{"ok": false, "broken_at": "<event-id>", ...}`, the restored
data was altered relative to when it was written (or the dump was corrupted);
treat this as a security event and restore from a known-good, checksum-verified
backup.

## Recovery objectives

| Objective | Target | How it is met |
|-----------|--------|---------------|
| RPO (data loss) | ≤ 24h (nightly) | Nightly `pg_dump`; shorten interval or add WAL archiving/PITR for tighter RPO. |
| RTO (time to restore) | ≤ 1h | Single `pg_restore` into a rebuilt TimescaleDB container; services are stateless. |
| Integrity | Tamper-evident | Append-only audit chain + `GET /api/v1/audit/verify` after restore; off-host WORM storage of dumps. |

For sub-daily RPO, enable PostgreSQL WAL archiving / point-in-time recovery
(PITR) on the managed/production database in addition to these logical dumps.
