#!/usr/bin/env bash
#
# backup_audit_db.sh — pg_dump-based backup of the S3M-WaterTwin
# Timescale/audit database (telemetry hypertable, tamper-evident audit trail,
# and recommendations). See docs/deployment/backup-recovery.md for restore and
# scheduling guidance.
#
# The dump is a plain custom-format archive (pg_dump -Fc) that captures the full
# schema + data, including the append-only audit hash chain, so a restore
# reproduces a chain that still verifies via GET /api/v1/audit/verify.
#
# Connection is resolved in this order:
#   1. $WATERTWIN_DATABASE_URL (a libpq/psql connection URI), or
#   2. individual PG* variables (PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE).
#
# When the local `pg_dump` binary is unavailable, the script transparently runs
# pg_dump inside the running TimescaleDB container ($PG_CONTAINER, default
# watertwin-timescaledb) via `docker exec`.
#
# Usage:
#   scripts/backup_audit_db.sh [output_dir]
#
# Environment:
#   WATERTWIN_DATABASE_URL   postgres connection URI (preferred)
#   PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE   discrete conn params
#   BACKUP_DIR               output directory (default: ./backups; arg overrides)
#   BACKUP_RETENTION_DAYS    delete dumps older than N days (default: 30; 0=keep)
#   PG_CONTAINER             docker container name for the fallback path
#
set -euo pipefail

# --- defaults (match docker-compose.yml) -----------------------------------
DB_URL="${WATERTWIN_DATABASE_URL:-}"
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-watertwin}"
PGDATABASE="${PGDATABASE:-watertwin}"
PG_CONTAINER="${PG_CONTAINER:-watertwin-timescaledb}"
BACKUP_DIR="${1:-${BACKUP_DIR:-./backups}}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
outfile="${BACKUP_DIR}/watertwin-audit-${timestamp}.dump"

echo "[backup] target: ${outfile}"

run_pg_dump_local() {
  # Prefer the connection URI when provided; otherwise use PG* variables.
  if [[ -n "$DB_URL" ]]; then
    pg_dump --format=custom --no-owner --no-privileges --file="$outfile" "$DB_URL"
  else
    PGPASSWORD="${PGPASSWORD:-watertwin}" pg_dump \
      --format=custom --no-owner --no-privileges \
      --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" \
      --file="$outfile" "$PGDATABASE"
  fi
}

run_pg_dump_docker() {
  # Stream a custom-format dump out of the container to the host file.
  echo "[backup] local pg_dump not found; using docker exec ${PG_CONTAINER}"
  if [[ -n "$DB_URL" ]]; then
    docker exec "$PG_CONTAINER" pg_dump --format=custom --no-owner --no-privileges \
      "$DB_URL" > "$outfile"
  else
    docker exec -e PGPASSWORD="${PGPASSWORD:-watertwin}" "$PG_CONTAINER" pg_dump \
      --format=custom --no-owner --no-privileges \
      --username="$PGUSER" "$PGDATABASE" > "$outfile"
  fi
}

if command -v pg_dump >/dev/null 2>&1; then
  run_pg_dump_local
elif command -v docker >/dev/null 2>&1; then
  run_pg_dump_docker
else
  echo "[backup] ERROR: neither pg_dump nor docker is available." >&2
  exit 1
fi

# Integrity checksum alongside the dump, for tamper-evidence of the backup file.
if command -v sha256sum >/dev/null 2>&1; then
  ( cd "$BACKUP_DIR" && sha256sum "$(basename "$outfile")" > "$(basename "$outfile").sha256" )
  echo "[backup] checksum: ${outfile}.sha256"
fi

size="$(du -h "$outfile" | cut -f1)"
echo "[backup] OK: wrote ${outfile} (${size})"

# --- retention -------------------------------------------------------------
if [[ "$BACKUP_RETENTION_DAYS" -gt 0 ]]; then
  echo "[backup] pruning dumps older than ${BACKUP_RETENTION_DAYS} day(s) in ${BACKUP_DIR}"
  find "$BACKUP_DIR" -maxdepth 1 -type f -name 'watertwin-audit-*.dump*' \
    -mtime "+${BACKUP_RETENTION_DAYS}" -print -delete || true
fi

echo "[backup] done."
