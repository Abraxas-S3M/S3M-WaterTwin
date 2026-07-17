"use strict";

// S3M-WaterTwin Simulation Center dashboard.
// Read-only advisory client. Talks to watertwin-api via the nginx proxy
// (/health and /api/*). Handles loading / empty / offline / error states.

const $ = (id) => document.getElementById(id);

const el = {
  offlineBanner: $("offline-banner"),
  retryBtn: $("retry-btn"),
  healthDot: $("health-dot"),
  healthText: $("health-text"),
  pumpSelect: $("pump-select"),
  leakNodeSelect: $("leak-node-select"),
  leakArea: $("leak-area"),
  leakCd: $("leak-cd"),
  runBtn: $("run-btn"),
  runStatus: $("run-status"),
  emptyState: $("empty-state"),
  loadingState: $("loading-state"),
  errorState: $("error-state"),
  errorMessage: $("error-message"),
  errorDismiss: $("error-dismiss"),
  results: $("results"),
  kpiBaseline: $("kpi-baseline"),
  kpiScenario: $("kpi-scenario"),
  kpiDelta: $("kpi-delta"),
  kpiConfidence: $("kpi-confidence"),
  pressureTable: $("pressure-table").querySelector("tbody"),
  flowTable: $("flow-table").querySelector("tbody"),
  violations: $("violations"),
  reco: $("reco"),
  recoActions: $("reco-actions"),
  approveBtn: $("approve-btn"),
  rejectBtn: $("reject-btn"),
  reportBtn: $("report-btn"),
  decisionStatus: $("decision-status"),
};

let currentScenario = "pump_outage";
let lastRun = null; // { jobId, recommendationId }
let healthTimer = null;

const fmt = (v, digits = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toFixed(digits);

function setOffline(isOffline) {
  el.offlineBanner.classList.toggle("hidden", !isOffline);
  el.runBtn.disabled = isOffline;
  if (isOffline) {
    el.healthDot.className = "dot dot-bad";
    el.healthText.textContent = "offline";
  }
}

function showOnly(section) {
  for (const s of [el.emptyState, el.loadingState, el.errorState, el.results]) {
    s.classList.add("hidden");
  }
  if (section) section.classList.remove("hidden");
}

async function api(path, options) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body && body.detail) detail = body.detail;
    } catch (_) {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return resp;
}

// -- Health / connectivity ---------------------------------------------------

async function pollHealth() {
  try {
    const resp = await api("/health");
    const body = await resp.json();
    setOffline(false);
    const ok = body.status === "healthy";
    el.healthDot.className = ok ? "dot dot-ok" : "dot dot-bad";
    const db = body.db_connected ? "db✓" : "db·mem";
    const sim = body.hydraulic_sim_reachable ? "sim✓" : "sim✗";
    el.healthText.textContent = `${ok ? "healthy" : "degraded"} · ${sim} · ${db}`;
    el.runBtn.disabled = false;
  } catch (err) {
    setOffline(true);
  }
}

// -- Network form ------------------------------------------------------------

function fillSelect(select, items) {
  select.innerHTML = "";
  if (!items || items.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "none available";
    opt.disabled = true;
    select.appendChild(opt);
    return;
  }
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item;
    opt.textContent = item;
    select.appendChild(opt);
  }
}

async function loadNetwork() {
  try {
    const resp = await api("/api/v1/simulation-center/network");
    const info = await resp.json();
    fillSelect(el.pumpSelect, info.pumps);
    fillSelect(el.leakNodeSelect, info.demand_nodes || info.demandNodes);
  } catch (err) {
    fillSelect(el.pumpSelect, []);
    fillSelect(el.leakNodeSelect, []);
    el.runStatus.textContent = `Could not load network: ${err.message}`;
  }
}

// -- Rendering ---------------------------------------------------------------

function renderDeltaRows(tbody, baselineMap, scenarioMap, deltaMap) {
  tbody.innerHTML = "";
  const keys = Object.keys(deltaMap || {}).sort();
  if (keys.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="4" class="muted">No significant change</td>`;
    tbody.appendChild(tr);
    return;
  }
  for (const key of keys) {
    const base = baselineMap ? baselineMap[key] : undefined;
    const scen = scenarioMap ? scenarioMap[key] : undefined;
    const delta = deltaMap[key];
    const cls = delta < 0 ? "neg" : delta > 0 ? "pos" : "";
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${key}</td><td>${fmt(base)}</td><td>${fmt(scen)}</td>` +
      `<td class="${cls}">${fmt(delta)}</td>`;
    tbody.appendChild(tr);
  }
}

function renderViolations(violations) {
  el.violations.innerHTML = "";
  if (!violations || violations.length === 0) {
    el.violations.innerHTML = `<li class="muted">None</li>`;
    return;
  }
  for (const v of violations) {
    const li = document.createElement("li");
    li.className = v.severity === "critical" ? "critical" : "warn";
    li.textContent = `${v.element_id} · ${v.metric} = ${fmt(v.value)} (limit ${fmt(v.limit)}) — ${v.description}`;
    el.violations.appendChild(li);
  }
}

function renderRecommendation(reco) {
  el.decisionStatus.textContent = "";
  if (!reco) {
    el.reco.className = "muted";
    el.reco.textContent = "No recommendation.";
    el.recoActions.classList.add("hidden");
    return;
  }
  el.reco.className = "";
  el.reco.innerHTML =
    `<div class="summary">${reco.summary || ""}</div>` +
    `<div class="action">${reco.recommended_action || ""}</div>`;
  el.recoActions.classList.remove("hidden");
}

function renderRun(run) {
  const comp = run.comparison || {};
  el.kpiBaseline.textContent = fmt(comp.delivered_flow_baseline_m3h);
  el.kpiScenario.textContent = fmt(comp.delivered_flow_scenario_m3h);
  el.kpiDelta.textContent = fmt(comp.delivered_flow_delta_m3h);
  el.kpiConfidence.textContent = fmt(run.confidence, 2);

  const baseOut = (run.baseline || {}).outputs || {};
  const scenOut = (run.scenario_result || {}).outputs || {};
  renderDeltaRows(el.pressureTable, baseOut.node_pressure_m, scenOut.node_pressure_m, comp.pressure_delta_m);
  renderDeltaRows(el.flowTable, baseOut.link_flow_m3h, scenOut.link_flow_m3h, comp.flow_delta_m3h);
  renderViolations((run.scenario_result || {}).constraint_violations);
  renderRecommendation(run.recommendation);

  lastRun = {
    jobId: (run.scenario_result || {}).job_id,
    recommendationId: run.recommendation ? run.recommendation.recommendation_id : null,
  };
  showOnly(el.results);
}

// -- Actions -----------------------------------------------------------------

function buildRequest() {
  if (currentScenario === "pump_outage") {
    return { scenario: "pump_outage", parameters: { pump_id: el.pumpSelect.value } };
  }
  return {
    scenario: "leak",
    parameters: {
      node_id: el.leakNodeSelect.value,
      area_m2: Number(el.leakArea.value),
      discharge_coeff: Number(el.leakCd.value),
    },
  };
}

async function runScenario() {
  el.runBtn.disabled = true;
  el.runStatus.textContent = "";
  showOnly(el.loadingState);
  try {
    const resp = await api("/api/v1/simulation-center/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildRequest()),
    });
    const run = await resp.json();
    renderRun(run);
  } catch (err) {
    el.errorMessage.textContent = err.message;
    showOnly(el.errorState);
  } finally {
    el.runBtn.disabled = false;
  }
}

async function decide(status) {
  if (!lastRun || !lastRun.recommendationId) return;
  el.decisionStatus.textContent = "saving…";
  try {
    const resp = await api(`/api/v1/recommendations/${lastRun.recommendationId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, actor: "operator" }),
    });
    const card = await resp.json();
    el.decisionStatus.textContent = `Recommendation ${card.approval_status} · audited`;
  } catch (err) {
    el.decisionStatus.textContent = `Failed: ${err.message}`;
  }
}

async function downloadReport() {
  if (!lastRun || !lastRun.jobId) return;
  el.decisionStatus.textContent = "generating report…";
  try {
    const resp = await api(`/api/v1/reports/scenario/${lastRun.jobId}`, { method: "POST" });
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `scenario-report-${lastRun.jobId}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    el.decisionStatus.textContent = "report downloaded";
  } catch (err) {
    el.decisionStatus.textContent = `Report failed: ${err.message}`;
  }
}

// -- Wiring ------------------------------------------------------------------

function selectScenario(scenario) {
  currentScenario = scenario;
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.scenario === scenario);
  });
  $("params-pump_outage").classList.toggle("hidden", scenario !== "pump_outage");
  $("params-leak").classList.toggle("hidden", scenario !== "leak");
}

function init() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => selectScenario(tab.dataset.scenario));
  });
  el.runBtn.addEventListener("click", runScenario);
  el.approveBtn.addEventListener("click", () => decide("approved"));
  el.rejectBtn.addEventListener("click", () => decide("rejected"));
  el.reportBtn.addEventListener("click", downloadReport);
  el.errorDismiss.addEventListener("click", () => showOnly(el.emptyState));
  el.retryBtn.addEventListener("click", () => {
    pollHealth();
    loadNetwork();
  });

  showOnly(el.emptyState);
  pollHealth();
  loadNetwork();
  healthTimer = setInterval(pollHealth, 10000);
}

document.addEventListener("DOMContentLoaded", init);
