// Simulation Center front-end. Calls watertwin-api through the nginx /api proxy.
const API = window.WATERTWIN_API_BASE || "";

let currentScenario = "pump_outage";

const $ = (id) => document.getElementById(id);

async function checkHealth() {
  try {
    const r = await fetch(`${API}/health`);
    const body = await r.json();
    const ok = body.status === "healthy" && body.hydraulic_sim_reachable;
    $("health-dot").className = "dot " + (ok ? "dot-ok" : "dot-bad");
    $("health-text").textContent = ok ? "hydraulic-sim healthy" : "hydraulic-sim unreachable";
  } catch (e) {
    $("health-dot").className = "dot dot-bad";
    $("health-text").textContent = "API unreachable";
  }
}

async function loadNetwork() {
  try {
    const r = await fetch(`${API}/api/v1/simulation-center/network`);
    const net = await r.json();
    const pumpSel = $("pump-select");
    pumpSel.innerHTML = "";
    (net.pumps || []).forEach((p) => {
      const o = document.createElement("option");
      o.value = p; o.textContent = p; pumpSel.appendChild(o);
    });
    if (pumpSel.options.length > 1) pumpSel.selectedIndex = pumpSel.options.length - 1;

    const leakSel = $("leak-node-select");
    leakSel.innerHTML = "";
    (net.demand_nodes || []).forEach((n) => {
      const o = document.createElement("option");
      o.value = n; o.textContent = n; leakSel.appendChild(o);
    });
  } catch (e) {
    $("run-status").textContent = "Could not load network metadata.";
  }
}

function selectScenario(scenario) {
  currentScenario = scenario;
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.scenario === scenario)
  );
  $("params-pump_outage").classList.toggle("hidden", scenario !== "pump_outage");
  $("params-leak").classList.toggle("hidden", scenario !== "leak");
}

function fmt(v, d = 1) {
  return v === null || v === undefined ? "–" : Number(v).toFixed(d);
}

function buildParams() {
  if (currentScenario === "pump_outage") {
    return { pump_id: $("pump-select").value };
  }
  return {
    node_id: $("leak-node-select").value,
    area_m2: parseFloat($("leak-area").value),
    discharge_coeff: parseFloat($("leak-cd").value),
  };
}

function renderDeltaTable(tbodyId, baselineMap, scenarioMap, deltaMap) {
  const tbody = document.querySelector(`#${tbodyId} tbody`);
  tbody.innerHTML = "";
  Object.keys(deltaMap).sort().forEach((k) => {
    const b = baselineMap[k], s = scenarioMap[k], d = deltaMap[k];
    const tr = document.createElement("tr");
    const cls = d < -0.05 ? "delta-neg" : d > 0.05 ? "delta-pos" : "";
    tr.innerHTML = `<td>${k}</td><td>${fmt(b)}</td><td>${fmt(s)}</td><td class="${cls}">${fmt(d)}</td>`;
    tbody.appendChild(tr);
  });
}

function renderViolations(list) {
  const ul = $("violations");
  ul.innerHTML = "";
  if (!list || list.length === 0) {
    ul.innerHTML = '<li class="muted">None</li>';
    return;
  }
  list.forEach((v) => {
    const li = document.createElement("li");
    if (v.severity === "critical") li.classList.add("critical");
    li.textContent = `${v.element_id}: ${v.description}`;
    ul.appendChild(li);
  });
}

function renderRecommendation(reco) {
  const el = $("reco");
  if (!reco) { el.className = "muted"; el.textContent = "No recommendation."; return; }
  el.className = "";
  const simTags = (reco.evidence.simulation_ids || [])
    .map((s) => `<span class="tag">sim: ${s}</span>`).join("");
  el.innerHTML = `
    <p><strong>${reco.summary}</strong></p>
    <div class="action"><strong>Recommended action:</strong> ${reco.recommended_action}</div>
    <p class="muted" style="margin-top:10px">Confidence ${(reco.confidence * 100).toFixed(0)}% ·
      approval required · control write disabled</p>
    <div>${simTags}</div>`;
}

async function run() {
  const btn = $("run-btn");
  btn.disabled = true;
  $("run-status").textContent = "Running EPANET what-if…";
  try {
    const r = await fetch(`${API}/api/v1/simulation-center/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scenario: currentScenario,
        parameters: buildParams(),
        create_recommendation: true,
      }),
    });
    if (!r.ok) throw new Error(`API ${r.status}`);
    const body = await r.json();
    const c = body.comparison;

    $("kpi-baseline").textContent = fmt(c.delivered_flow_baseline_m3h);
    $("kpi-scenario").textContent = fmt(c.delivered_flow_scenario_m3h);
    const delta = $("kpi-delta");
    delta.textContent = fmt(c.delivered_flow_delta_m3h);
    delta.className = "kpi-value " + (c.delivered_flow_delta_m3h < 0 ? "bad" : "good");
    $("kpi-confidence").textContent = (body.confidence * 100).toFixed(0) + "%";

    renderDeltaTable(
      "pressure-table",
      body.baseline.outputs.node_pressure_m,
      body.scenario_result.outputs.node_pressure_m,
      c.pressure_delta_m
    );
    renderDeltaTable(
      "flow-table",
      body.baseline.outputs.link_flow_m3h,
      body.scenario_result.outputs.link_flow_m3h,
      c.flow_delta_m3h
    );
    renderViolations(body.scenario_result.constraint_violations);
    renderRecommendation(body.recommendation);

    $("results").classList.remove("hidden");
    $("run-status").textContent =
      `Done · scenario "${body.scenario}" · provenance ${body.scenario_result.provenance} · status ${body.scenario_result.status}`;
  } catch (e) {
    $("run-status").textContent = "Simulation failed: " + e.message;
  } finally {
    btn.disabled = false;
  }
}

document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => selectScenario(t.dataset.scenario))
);
$("run-btn").addEventListener("click", run);

checkHealth();
loadNetwork();
setInterval(checkHealth, 15000);
