#!/usr/bin/env bash
#
# dr_drill.sh — end-to-end disaster-recovery drill for the S3M-WaterTwin audit
# database. Exercises a pg_dump BACKUP (via scripts/backup_audit_db.sh) and a
# pg_restore RESTORE, then proves the tamper-evident audit hash chain still
# verifies after recovery.
#
# What it does
# ------------
#   1. Back up the live audit/Timescale database with scripts/backup_audit_db.sh.
#   2. Capture the live chain state (verify + count + head hash).
#   3. Simulate a disaster by restoring the dump into a FRESH database
#      (watertwin_dr_restore) with pg_restore — leaving the live DB untouched.
#   4. Verify the restored chain using the exact service logic (run inside the
#      watertwin-api container against the restored DB) and, when psycopg is
#      available on the host, additionally with scripts/verify_audit_chain.py.
#   5. Assert the restored chain is intact and identical (count + head) to the
#      live chain, then clean up the restore database.
#
# Requirements: docker (compose stack running) and python3 on the host.
# Usage:        scripts/dr_drill.sh
#
# See docs/deployment/dr-runbook.md for the full runbook and manual procedure.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PG_CONTAINER="${PG_CONTAINER:-watertwin-timescaledb}"
API_CONTAINER="${API_CONTAINER:-watertwin-api}"
PGUSER="${PGUSER:-watertwin}"
PGDATABASE="${PGDATABASE:-watertwin}"
RESTORE_DB="${RESTORE_DB:-watertwin_dr_restore}"
DB_HOST_IN_NET="${DB_HOST_IN_NET:-timescaledb}"
BACKUP_DIR="${BACKUP_DIR:-$(mktemp -d)}"
KEEP="${DR_KEEP:-0}"

log()  { echo "[dr] $*"; }
fail() { echo "[dr] FAIL: $*" >&2; exit 1; }

# Extract a field from a one-line JSON blob using python3 (jq-free).
jget() { python3 -c 'import sys,json;print(json.load(sys.stdin).get(sys.argv[1],""))' "$1"; }

command -v docker >/dev/null 2>&1 || fail "docker is required"
docker inspect "$PG_CONTAINER"  >/dev/null 2>&1 || fail "container $PG_CONTAINER not running (start the stack)"
docker inspect "$API_CONTAINER" >/dev/null 2>&1 || fail "container $API_CONTAINER not running (start the stack)"

restore_dsn="postgresql://${PGUSER}:${PGUSER}@${DB_HOST_IN_NET}:5432/${RESTORE_DB}"

verify_in_container() { # dsn -> prints one-line JSON from Store.verify_chain()
  docker exec -e "WATERTWIN_DATABASE_URL=$1" "$API_CONTAINER" \
    python -c 'import json,os; from app.store import Store; print(json.dumps(Store(os.environ["WATERTWIN_DATABASE_URL"]).verify_chain()))'
}

cleanup() {
  log "dropping restore database ${RESTORE_DB}"
  docker exec "$PG_CONTAINER" psql -U "$PGUSER" -d "$PGDATABASE" \
    -c "DROP DATABASE IF EXISTS ${RESTORE_DB} WITH (FORCE);" >/dev/null 2>&1 || true
  if [[ "$KEEP" != "1" ]]; then
    rm -rf "$BACKUP_DIR" 2>/dev/null || true
  else
    log "DR_KEEP=1 -> keeping backup dir ${BACKUP_DIR}"
  fi
}
trap cleanup EXIT

# --- 1. backup -------------------------------------------------------------
log "backing up the audit database (scripts/backup_audit_db.sh) ..."
BACKUP_DIR="$BACKUP_DIR" BACKUP_RETENTION_DAYS=0 bash scripts/backup_audit_db.sh "$BACKUP_DIR" >/dev/null
dump="$(ls -1t "$BACKUP_DIR"/watertwin-audit-*.dump 2>/dev/null | head -1 || true)"
[[ -n "$dump" ]] || fail "backup did not produce a dump in ${BACKUP_DIR}"
log "backup written: ${dump}"

# Confirm the dump's checksum (tamper-evidence of the backup file itself).
if [[ -f "${dump}.sha256" ]]; then
  ( cd "$BACKUP_DIR" && sha256sum -c "$(basename "$dump").sha256" >/dev/null ) \
    && log "backup checksum verified" || fail "backup checksum mismatch"
fi

# --- 2. capture the live chain state --------------------------------------
log "verifying the LIVE audit chain (pre-restore baseline) ..."
live_json="$(verify_in_container "postgresql://${PGUSER}:${PGUSER}@${DB_HOST_IN_NET}:5432/${PGDATABASE}")"
live_ok="$(echo "$live_json" | jget ok)"
live_count="$(echo "$live_json" | jget count)"
live_head="$(echo "$live_json" | jget head)"
log "live chain: ok=${live_ok} count=${live_count} head=${live_head:0:16}..."
[[ "$live_ok" == "True" ]] || fail "live audit chain is not valid before the drill: ${live_json}"

# --- 3. simulate disaster + restore into a fresh database ------------------
log "restoring the dump into a fresh database (${RESTORE_DB}) ..."
docker exec "$PG_CONTAINER" psql -U "$PGUSER" -d "$PGDATABASE" \
  -c "DROP DATABASE IF EXISTS ${RESTORE_DB} WITH (FORCE);" \
  -c "CREATE DATABASE ${RESTORE_DB};" >/dev/null
docker cp "$dump" "${PG_CONTAINER}:/tmp/dr-restore.dump" >/dev/null
docker exec "$PG_CONTAINER" pg_restore --no-owner --no-privileges \
  -U "$PGUSER" -d "$RESTORE_DB" /tmp/dr-restore.dump >/dev/null 2>&1 \
  || fail "pg_restore failed"
docker exec "$PG_CONTAINER" rm -f /tmp/dr-restore.dump >/dev/null 2>&1 || true

# --- 4. verify the restored chain -----------------------------------------
log "verifying the RESTORED audit chain (service logic, in-container) ..."
restored_json="$(verify_in_container "$restore_dsn")"
restored_ok="$(echo "$restored_json" | jget ok)"
restored_count="$(echo "$restored_json" | jget count)"
restored_head="$(echo "$restored_json" | jget head)"
log "restored chain: ok=${restored_ok} count=${restored_count} head=${restored_head:0:16}..."

# Best-effort: also demonstrate the standalone off-host verifier when the host
# has psycopg (the restore DB is reachable via the mapped 5432 port).
if python3 -c "import psycopg" >/dev/null 2>&1; then
  log "cross-checking with scripts/verify_audit_chain.py (host psycopg) ..."
  host_dsn="postgresql://${PGUSER}:${PGUSER}@localhost:5432/${RESTORE_DB}"
  python3 scripts/verify_audit_chain.py --database-url "$host_dsn" >/dev/null \
    && log "standalone verifier agrees: chain intact" \
    || fail "standalone verifier reported a broken chain"
else
  log "(host psycopg not installed; skipping standalone-verifier cross-check)"
fi

# --- 5. assertions ---------------------------------------------------------
echo "----------------------------------------------------------------------"
[[ "$restored_ok" == "True" ]] || fail "RESTORED audit chain is BROKEN: ${restored_json}"
log "PASS: restored audit chain verifies (ok=true)"

[[ "$restored_count" == "$live_count" ]] \
  || fail "event count changed across restore: live=${live_count} restored=${restored_count}"
log "PASS: event count preserved (${restored_count})"

[[ "$restored_head" == "$live_head" ]] \
  || fail "chain head changed across restore: live=${live_head} restored=${restored_head}"
log "PASS: chain head hash identical after restore"
echo "----------------------------------------------------------------------"
log "DR DRILL PASSED: pg_dump/pg_restore recovered the database and the"
log "tamper-evident audit chain is intact and identical post-restore."
