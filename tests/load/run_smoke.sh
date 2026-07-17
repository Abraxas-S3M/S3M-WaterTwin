#!/usr/bin/env bash
#
# run_smoke.sh — run the k6 load test's CI-friendly smoke profile.
#
# By default this boots a local, in-memory watertwin-api (auth disabled, no
# database) and runs the smoke profile against it, so it is fully self-contained
# for CI and local dev. Point it at an already-running API by setting BASE_URL.
#
# Environment:
#   LOAD_PROFILE   smoke | load | soak (default smoke)
#   BASE_URL       target API; when set, no local API is booted
#   API_PORT       port for the booted local API (default 8000)
#   INGEST_TOKEN   X-Ingest-Token for the ingest path (optional)
#   AUTH_TOKEN     bearer token for read endpoints when auth is enforced (optional)
#
# Requires: k6 (https://k6.io/docs/get-started/installation/) and, when booting a
# local API, python3 with the watertwin-api requirements installed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROFILE="${LOAD_PROFILE:-smoke}"
API_PORT="${API_PORT:-8000}"
BASE_URL="${BASE_URL:-}"
K6_SCRIPT="${REPO_ROOT}/tests/load/k6/ingest_read.js"

if ! command -v k6 >/dev/null 2>&1; then
  echo "[load] ERROR: k6 not found. Install it: https://k6.io/docs/get-started/installation/" >&2
  exit 127
fi

api_pid=""
cleanup() { [[ -n "$api_pid" ]] && kill "$api_pid" >/dev/null 2>&1 || true; }
trap cleanup EXIT

if [[ -z "$BASE_URL" ]]; then
  BASE_URL="http://127.0.0.1:${API_PORT}"
  echo "[load] booting a local in-memory watertwin-api (auth disabled) on :${API_PORT}"
  export WATERTWIN_AUTH_DISABLED=true
  unset WATERTWIN_DATABASE_URL WATERTWIN_INGEST_TOKEN 2>/dev/null || true
  export PYTHONPATH="${REPO_ROOT}/packages:${REPO_ROOT}/services/watertwin-api"
  ( cd "${REPO_ROOT}/services/watertwin-api" \
      && exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port "${API_PORT}" \
         >/tmp/watertwin-api-load.log 2>&1 ) &
  api_pid=$!

  echo "[load] waiting for API health ..."
  ready=0
  for _ in $(seq 1 60); do
    if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then ready=1; break; fi
    if ! kill -0 "$api_pid" 2>/dev/null; then
      echo "[load] ERROR: API process exited early. Log:" >&2
      cat /tmp/watertwin-api-load.log >&2 || true
      exit 1
    fi
    sleep 1
  done
  if [[ "$ready" -ne 1 ]]; then
    echo "[load] ERROR: API did not become healthy in time. Log:" >&2
    cat /tmp/watertwin-api-load.log >&2 || true
    exit 1
  fi
fi

echo "[load] running k6 profile='${PROFILE}' against ${BASE_URL}"
LOAD_PROFILE="$PROFILE" \
BASE_URL="$BASE_URL" \
INGEST_TOKEN="${INGEST_TOKEN:-}" \
AUTH_TOKEN="${AUTH_TOKEN:-}" \
  k6 run "$K6_SCRIPT"
