// k6 load test for S3M-WaterTwin: telemetry ingest + API read paths.
//
// Exercises the two hot paths of the platform:
//   * ingest  -> POST /api/v1/ingestion/telemetry (edge store-and-forward dest)
//   * read    -> GET  /health, /api/v1/ingestion/source,
//                     /api/v1/ingestion/telemetry/stats, /api/v1/audit/verify,
//                     /api/v1/recommendations
//
// Profiles (set LOAD_PROFILE):
//   smoke  (default) -- tiny, fast, CI-friendly: a couple of VUs for ~20s with
//                       lenient-but-real thresholds. Meant to catch gross
//                       regressions / breakage, not to benchmark.
//   load             -- steady moderate load for a few minutes.
//   soak             -- longer steady load to surface leaks/drift.
//
// Environment:
//   BASE_URL       API base URL (default http://localhost:8000)
//   LOAD_PROFILE   smoke | load | soak (default smoke)
//   INGEST_TOKEN   value sent as the X-Ingest-Token header (optional)
//   AUTH_TOKEN     bearer token for read endpoints when auth is enforced (optional)
//   VU_ID_PREFIX   batch-id prefix so ingest keys stay unique per run (default k6)
//
// Run:
//   k6 run tests/load/k6/ingest_read.js
//   LOAD_PROFILE=load BASE_URL=http://localhost:8000 k6 run tests/load/k6/ingest_read.js

import http from "k6/http";
import { check, sleep } from "k6";
import { Counter } from "k6/metrics";

const BASE_URL = (__ENV.BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const PROFILE = (__ENV.LOAD_PROFILE || "smoke").toLowerCase();
const INGEST_TOKEN = __ENV.INGEST_TOKEN || "";
const AUTH_TOKEN = __ENV.AUTH_TOKEN || "";
const ID_PREFIX = __ENV.VU_ID_PREFIX || "k6";

const ingestOk = new Counter("ingest_accepted");
const ingestDup = new Counter("ingest_duplicate");

const PROFILES = {
  smoke: {
    scenarios: {
      ingest: {
        executor: "constant-vus",
        vus: 2,
        duration: "20s",
        exec: "ingest",
      },
      read: {
        executor: "constant-vus",
        vus: 3,
        duration: "20s",
        exec: "read",
      },
    },
    thresholds: {
      // Smoke is a breakage gate, not a benchmark: generous but non-trivial.
      http_req_failed: ["rate<0.05"],
      http_req_duration: ["p(95)<1500"],
    },
  },
  load: {
    scenarios: {
      ingest: { executor: "constant-vus", vus: 10, duration: "3m", exec: "ingest" },
      read: { executor: "constant-vus", vus: 20, duration: "3m", exec: "read" },
    },
    thresholds: {
      http_req_failed: ["rate<0.01"],
      http_req_duration: ["p(95)<800"],
    },
  },
  soak: {
    scenarios: {
      ingest: { executor: "constant-vus", vus: 8, duration: "30m", exec: "ingest" },
      read: { executor: "constant-vus", vus: 12, duration: "30m", exec: "read" },
    },
    thresholds: {
      http_req_failed: ["rate<0.01"],
      http_req_duration: ["p(95)<1000"],
    },
  },
};

const chosen = PROFILES[PROFILE] || PROFILES.smoke;
export const options = { scenarios: chosen.scenarios, thresholds: chosen.thresholds };

function ingestHeaders() {
  const h = { "Content-Type": "application/json" };
  if (INGEST_TOKEN) h["X-Ingest-Token"] = INGEST_TOKEN;
  return h;
}

function readHeaders() {
  const h = {};
  if (AUTH_TOKEN) h["Authorization"] = `Bearer ${AUTH_TOKEN}`;
  return h;
}

function buildBatch() {
  // Unique, stable batch id per (VU, iteration) so ingest idempotency keys never
  // collide across the run.
  const batchId = `${ID_PREFIX}-vu${__VU}-it${__ITER}`;
  const ts = new Date().toISOString();
  const assets = ["PU-PROD-1", "PU-PROD-2", "RO-TRAIN-001"];
  const readings = assets.map((asset, i) => ({
    asset_id: asset,
    metric: "vibration_mm_s",
    value: 2.5 + (i + (__ITER % 10)) * 0.1,
    unit: "mm/s",
    timestamp: ts,
    provenance: "synthetic",
    quality: "good",
  }));
  return { batch_id: batchId, readings: readings, source: `${ID_PREFIX}-vu${__VU}` };
}

export function ingest() {
  const res = http.post(
    `${BASE_URL}/api/v1/ingestion/telemetry`,
    JSON.stringify(buildBatch()),
    { headers: ingestHeaders() }
  );
  const ok = check(res, {
    "ingest status 200": (r) => r.status === 200,
    "ingest accepted or duplicate": (r) => {
      if (r.status !== 200) return false;
      const body = r.json();
      return body.accepted >= 0 && typeof body.duplicate === "boolean";
    },
  });
  if (ok && res.status === 200) {
    const body = res.json();
    if (body.duplicate) ingestDup.add(1);
    else ingestOk.add(1);
  }
  sleep(0.2);
}

export function read() {
  const rh = readHeaders();
  const health = http.get(`${BASE_URL}/health`);
  check(health, { "health 200": (r) => r.status === 200 });

  const source = http.get(`${BASE_URL}/api/v1/ingestion/source`, { headers: rh });
  check(source, { "source ok": (r) => r.status === 200 || r.status === 401 });

  const stats = http.get(`${BASE_URL}/api/v1/ingestion/telemetry/stats`, { headers: rh });
  check(stats, { "stats ok": (r) => r.status === 200 || r.status === 401 });

  const verify = http.get(`${BASE_URL}/api/v1/audit/verify`, { headers: rh });
  check(verify, {
    "audit verify ok": (r) => {
      if (r.status === 401 || r.status === 403) return true; // auth-gated; not a load failure
      return r.status === 200 && r.json().ok === true;
    },
  });

  const recos = http.get(`${BASE_URL}/api/v1/recommendations`, { headers: rh });
  check(recos, { "recommendations ok": (r) => r.status === 200 || r.status === 401 });

  sleep(0.3);
}
