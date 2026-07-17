# S3M-WaterTwin — Guided Demo Script

A start-to-finish walkthrough of the advisory digital twin: from normal
operations, through an injected high-pressure-pump (HPP) degradation, to an
approved-and-audited advisory recommendation and a clean reset.

Everything below is **read-only and advisory**. Nothing in this platform can
command a pump, valve, VFD, or dosing system. Every response carries the control
boundary (`control_write_enabled=false`) and all figures are provenance-tagged
simulated / preliminary what-if output — never a validated prediction or a
control action.

---

## 0. Bring up the stack

One command brings up the whole persistent stack (TimescaleDB, hydraulic-sim,
treatment-sim, watertwin-api, dashboard):

```bash
docker compose up --build -d
docker compose ps          # wait until every service is "healthy"
```

Endpoints:

| Surface | URL |
| --- | --- |
| Operator dashboard (Simulation Center) | http://localhost:8080 |
| watertwin-api | http://localhost:8000 |
| hydraulic-sim (EPANET/WNTR) | http://localhost:8100 |
| treatment-sim (WaterTAP/IDAES) | http://localhost:8081 |
| TimescaleDB | localhost:5432 (`watertwin`/`watertwin`) |

> **Demo accounts.** This reference deployment ships **no authentication** — it
> is a read-only advisory demo, so treat every session as an unauthenticated
> `operator` in a sandbox. Sign-in, RBAC, and per-tenant accounts are part of
> the commercial hardening work package (Keycloak / SSO), deliberately deferred.

Convenience make targets:

```bash
make up               # docker compose up --build -d
make scenario-degrade # inject the HPP/pump-outage degradation what-if
make reset            # clear cached runs, recommendations, and audit trail
make down             # stop the stack
```

---

## 1. Normal operations

Open the dashboard at http://localhost:8080. Confirm:

- The header shows the **READ-ONLY · ADVISORY** pill and a green health dot with
  `healthy · sim✓ · db✓` (the API is reachable, hydraulic-sim is reachable, and
  the TimescaleDB store is connected).
- The scenario form is populated from the live network model (pump list, leak
  nodes). This confirms `watertwin-api → hydraulic-sim` connectivity.

From the API directly:

```bash
curl -s http://localhost:8000/health | jq '{status, hydraulic_sim_reachable, db_connected, control_write_enabled}'
curl -s http://localhost:8000/api/v1/simulation-center/network | jq '{train_id, pumps}'
```

Baseline delivered flow for `RO-TRAIN-001` is ~560 m³/h with all handoff-node
pressures above the 25 m minimum. This is the healthy operating point.

---

## 2. Inject an HPP degradation (health falls, cavitation risk rises)

Model a degrading / lost high-pressure product pump by taking a duty pump
offline. In the dashboard: select **Pump Outage**, choose `PU-PROD-2`, and click
**Run what-if**. Or from the CLI:

```bash
make scenario-degrade
# equivalently:
curl -s -X POST http://localhost:8000/api/v1/simulation-center/run \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"pump_outage","parameters":{"pump_id":"PU-PROD-2"}}' | jq '.comparison'
```

Observe the **health impact**:

- **Delivered flow falls** from ~560 to ~456 m³/h (≈ −18%). This is the headline
  degradation the dashboard surfaces in the KPI strip.
- **Handoff pressures collapse**: nodes `J-D1`, `J-D2`, `J-D3` drop below the
  25 m required minimum and appear as **constraint violations**. The minimum
  node pressure falls to ~16 m.
- **Cavitation risk rises**: as suction/handoff pressure approaches and crosses
  the low-pressure envelope, the remaining duty pump runs far from its best
  efficiency point with reduced NPSH margin — the low-pressure violations are the
  cavitation-risk signal. (These are advisory indicators derived from the
  read-only hydraulic what-if, not measured NPSH.)

The breakdown (per-node pressure delta, per-link flow delta) is shown in the
dashboard delta tables.

---

## 3. Ask S3M for a recommendation (quad-engine or local fallback)

Each non-baseline run asks the advisory reasoner for a recommendation. When an
S3M-Core quad-engine endpoint is configured and reachable it is used; otherwise
the platform uses the **local fallback reasoner**, so the demo always produces a
recommendation even fully offline.

The run response includes a recommendation card:

```bash
curl -s -X POST http://localhost:8000/api/v1/simulation-center/run \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"pump_outage","parameters":{"pump_id":"PU-PROD-2"}}' \
  | jq '.recommendation | {recommendation_id, summary, recommended_action, confidence, approval_status, evidence: .evidence.simulation_ids}'
```

The card explains the ranked cause (loss of parallel pumping capacity), the
recommended **advisory** response (stage the standby pump, pre-position crews,
keep handoff pressure above 25 m), a confidence, and the `simulation_ids` that
support it — full provenance back to the exact what-if run.

---

## 4. Pump-outage hydraulic sim (evidence)

The recommendation is backed by the read-only EPANET/WNTR hydraulic what-if run
in step 2. You can inspect the raw simulation job on hydraulic-sim:

```bash
# The scenario job id is in scenario_result.job_id of the run response.
curl -s http://localhost:8100/api/v1/hydraulics/network | jq '{pumps, valves, demand_nodes}'
```

Every hydraulic result is tagged `provenance="simulated"`, `status="preliminary"`
and carries the control boundary.

---

## 5. RO what-if (treatment-sim)

Cross-check the treatment side with a read-only RO process simulation
(WaterTAP/IDAES in the container; analytical reference model otherwise):

```bash
# Submit a baseline RO simulation.
JOB=$(curl -s -X POST http://localhost:8081/api/v1/process/simulate \
  -H 'Content-Type: application/json' \
  -d '{"feed":{"flow_m3h":420,"tds_mg_l":38000,"pressure_bar":60},"membrane":{"area_m2":37}}' \
  | jq -r '.job_id')

# Poll for the result.
curl -s http://localhost:8081/api/v1/process/jobs/$JOB | jq '{state, result}'

# Membrane-degradation what-if (specific energy + permeate impact).
curl -s -X POST http://localhost:8081/api/v1/process/membrane-degradation \
  -H 'Content-Type: application/json' \
  -d '{"feed":{"flow_m3h":420,"tds_mg_l":38000,"pressure_bar":60},"membrane":{"area_m2":37},"a_retention":0.8,"b_increase":1.6}'
```

Results carry recovery, permeate TDS, specific energy, and provenance — advisory
what-if only.

---

## 6. Approve the recommendation (operator decision)

Approval is an **operator action only** — it records a human decision, it never
writes to equipment. In the dashboard, click **Approve** on the recommendation
card. Or from the CLI:

```bash
REC=$(curl -s http://localhost:8000/api/v1/recommendations | jq -r '.[0].recommendation_id')
curl -s -X POST http://localhost:8000/api/v1/recommendations/$REC/decision \
  -H 'Content-Type: application/json' \
  -d '{"status":"approved","actor":"operator-1"}' | jq '{recommendation_id, approval_status}'
```

## 6a. Download the scenario report

Generate a self-contained, downloadable scenario report (baseline vs scenario,
impacts, recommended response, confidence, provenance, and the mandatory
read-only boundary footer). In the dashboard, click **Download report**. Or:

```bash
JID=<scenario_result.job_id from the run>
curl -s -X POST http://localhost:8000/api/v1/reports/scenario/$JID -o scenario-report.md
tail -n 8 scenario-report.md   # note the control-boundary footer
```

---

## 7. Audit trail

Every advisory action — scenario run, recommendation created, decision, report
generated, reset — is appended to the TimescaleDB-backed audit log:

```bash
curl -s 'http://localhost:8000/api/v1/audit?limit=20' | jq '.events[] | {ts, kind, actor, subject}'
```

You should see `scenario.run`, `recommendation.created`, `recommendation.decision`,
and `report.generated` events, in order.

---

## 8. Reset

Return the demo to a clean slate (clears cached runs, recommendations, and the
audit trail):

```bash
make reset
# equivalently:
curl -s -X POST http://localhost:8000/api/v1/reset | jq
```

Re-open the dashboard; it returns to the empty state, ready for the next run.

---

## What was (deliberately) not shown

Deferred to the commercial-hardening work package and intentionally **not** built
here: authentication / SSO (Keycloak), OT/SCADA connectivity, multi-tenancy, and
PostGIS spatial features. And — by design and enforced in CI — there is **no
control-write path** anywhere in the platform.
