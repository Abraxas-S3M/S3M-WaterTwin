#!/usr/bin/env bash
#
# edge_gateway_chaos.sh — kill the edge-gateway mid-stream and prove
# store-and-forward recovers with NO DATA LOSS, NO DUPLICATION, and a still-VALID
# tamper-evident audit chain.
#
# Scenario
# --------
#   1. Start a clean stack (fresh volumes) with the chaos overrides.
#   2. Let the gateway forward some telemetry to the API while it is healthy.
#   3. Stop the API so the gateway engages store-and-forward (spools to disk).
#   4. `docker kill` the edge-gateway MID-STREAM, with un-forwarded batches still
#      on its durable spool volume (simulates an edge crash).
#   5. Restart the gateway; it resumes producing and its spool volume is intact.
#   6. Bring the API back and let everything drain.
#   7. Assert every batch the gateway ever produced landed exactly once and the
#      audit hash chain still verifies.
#
# The ground truth for "everything produced" is the gateway's persisted spool
# sequence (`/data/spool/.next_seq`): total distinct batches ever created. Ingest
# is idempotent on batch_id, so a batch delivered-but-not-acked before the crash
# is de-duplicated on replay rather than double-counted.
#
# Requirements: docker (with compose v2) and python3 on the host.
# Usage:        tests/chaos/edge_gateway_chaos.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE=(docker compose -f docker-compose.yml -f tests/chaos/docker-compose.chaos.yml)
API_URL="${CHAOS_API_URL:-http://localhost:8000}"
GW_URL="${CHAOS_GW_URL:-http://localhost:8200}"
API_CTR="watertwin-api"
GW_CTR="watertwin-edge-gateway"
# Readings per batch — must match services/edge-gateway/app/generator.BATCH_SIZE.
BATCH_SIZE="${CHAOS_BATCH_SIZE:-7}"
KEEP_UP="${CHAOS_KEEP_UP:-0}"

log()  { echo "[chaos] $*"; }
fail() { echo "[chaos] FAIL: $*" >&2; exit 1; }

# jq-free JSON field extraction via python3.
jget() { python3 -c 'import sys,json;print(json.load(sys.stdin).get(sys.argv[1],""))' "$1"; }

curl_json() { curl -fsS "$1" 2>/dev/null; }

wait_health() { # url, name, timeout
  local url="$1" name="$2" timeout="${3:-90}" i
  for ((i = 0; i < timeout; i++)); do
    if curl -fsS "$url/health" >/dev/null 2>&1; then log "$name is healthy"; return 0; fi
    sleep 1
  done
  fail "$name did not become healthy within ${timeout}s"
}

gw_field() { curl_json "$GW_URL/stats" | jget "$1"; }

cleanup() {
  if [[ "$KEEP_UP" == "1" ]]; then
    log "CHAOS_KEEP_UP=1 -> leaving the stack running for inspection."
  else
    log "tearing down stack (down -v)"
    "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

command -v docker >/dev/null 2>&1 || fail "docker is required"

# --- 1. clean slate --------------------------------------------------------
log "starting a clean stack (fresh volumes) ..."
"${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
"${COMPOSE[@]}" up -d --build timescaledb watertwin-api edge-gateway
wait_health "$API_URL" "watertwin-api" 120
wait_health "$GW_URL" "edge-gateway" 60

# --- 2. let some telemetry flow while healthy ------------------------------
log "letting telemetry flow while healthy ..."
sleep 3
forwarded_before="$(gw_field forwarded)"
log "forwarded before outage: ${forwarded_before}"
[[ "${forwarded_before:-0}" -ge 1 ]] || fail "gateway did not forward anything while healthy"

# --- 3. outage: stop the API so the gateway spools -------------------------
log "stopping the API to engage store-and-forward ..."
"${COMPOSE[@]}" stop "$API_CTR" >/dev/null
log "waiting for the gateway spool to build up (store-and-forward) ..."
for ((i = 0; i < 60; i++)); do
  depth="$(gw_field spool_depth || echo 0)"
  [[ "${depth:-0}" -ge 5 ]] && break
  sleep 1
done
depth="$(gw_field spool_depth || echo 0)"
log "spool depth during outage: ${depth}"
[[ "${depth:-0}" -ge 1 ]] || fail "store-and-forward did not engage (spool stayed empty)"

# --- 4. kill the gateway MID-STREAM with un-forwarded data on disk ----------
log "KILLING the edge-gateway mid-stream (docker kill) ..."
docker kill "$GW_CTR" >/dev/null

# --- 5. restart the gateway; durable spool volume is intact -----------------
log "restarting the edge-gateway ..."
"${COMPOSE[@]}" up -d edge-gateway >/dev/null
wait_health "$GW_URL" "edge-gateway" 60

# --- 6. recover the API and let everything drain ---------------------------
log "restarting the API ..."
"${COMPOSE[@]}" start "$API_CTR" >/dev/null
wait_health "$API_URL" "watertwin-api" 120

log "waiting for the gateway to finish producing and fully drain its spool ..."
for ((i = 0; i < 120; i++)); do
  produced="$(gw_field produced || echo 0)"
  depth="$(gw_field spool_depth || echo 0)"
  reachable="$(gw_field api_reachable || echo False)"
  if [[ "${produced:-0}" -ge 30 && "${depth:-0}" -eq 0 && "$reachable" == "True" ]]; then
    break
  fi
  sleep 1
done
produced="$(gw_field produced || echo 0)"
depth="$(gw_field spool_depth || echo 0)"
log "final gateway state: produced(life2)=${produced} spool_depth=${depth}"
[[ "${depth:-1}" -eq 0 ]] || fail "spool did not fully drain (depth=${depth}); data would be stranded"

# --- 7. assertions ---------------------------------------------------------
# Ground truth: total distinct batches ever produced across BOTH lifetimes.
total_produced="$(docker exec "$GW_CTR" cat /data/spool/.next_seq 2>/dev/null | tr -d '[:space:]')"
[[ -n "$total_produced" ]] || fail "could not read persisted spool sequence"
log "total batches ever produced (persisted seq): ${total_produced}"

stats_json="$(curl_json "$API_URL/api/v1/ingestion/telemetry/stats")"
api_batches="$(echo "$stats_json" | jget batches)"
api_readings="$(echo "$stats_json" | jget readings)"
log "API ingested: batches=${api_batches} readings=${api_readings}"

verify_json="$(curl_json "$API_URL/api/v1/audit/verify")"
verify_ok="$(echo "$verify_json" | jget ok)"
verify_count="$(echo "$verify_json" | jget count)"
log "audit verify: ok=${verify_ok} count=${verify_count}"

expected_readings=$((total_produced * BATCH_SIZE))

echo "----------------------------------------------------------------------"
[[ "$api_batches" -eq "$total_produced" ]] \
  || fail "DATA LOSS: API has ${api_batches} batches but ${total_produced} were produced"
log "PASS: no data loss (all ${total_produced} produced batches were ingested)"

[[ "$api_readings" -eq "$expected_readings" ]] \
  || fail "DUPLICATION: API has ${api_readings} readings, expected ${expected_readings}"
log "PASS: no duplication (readings == batches x ${BATCH_SIZE})"

[[ "$verify_ok" == "True" ]] || fail "audit chain is BROKEN after recovery: ${verify_json}"
log "PASS: audit hash chain still verifies (ok=true)"

[[ "$verify_count" -eq "$total_produced" ]] \
  || fail "audit event count ${verify_count} != produced batches ${total_produced}"
log "PASS: exactly one audit event per ingested batch"
echo "----------------------------------------------------------------------"
log "CHAOS DRILL PASSED: store-and-forward recovered with no data loss, no"
log "duplication, and a valid audit chain."
