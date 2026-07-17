# S3M-WaterTwin

Digital-twin platform for reverse-osmosis (RO) desalination water treatment.

## Packages

- `packages/canonical_water_model` — shared canonical asset / stream / telemetry /
  packet / recommendation model (Pydantic v2).
- `packages/simulation_contracts` — shared what-if simulation request/result
  contracts (`provenance="simulated"`, `status="preliminary"`, read-only control
  boundary).

## Services

- `services/hydraulic-sim` — **read-only** hydraulic what-if simulation on the
  open-source **EPANET** engine via **WNTR**. Baseline, pump-outage, valve-closure,
  demand-change and leak scenarios for the RO-TRAIN-001 product-water handoff.
- `services/watertwin-api` — orchestration API for the dashboard Simulation
  Center; drives hydraulic-sim and attaches each run's `simulation_id` to
  recommendation `evidence.simulation_ids`.
- `dashboard` — static Simulation Center (nginx) showing baseline-vs-scenario
  pressure/flow deltas, confidence, and recommendations.

## Run the stack
Operator-facing digital twin for seawater reverse-osmosis (SWRO) water
treatment. **Advisory, no-write**: the system never writes to plant controls;
every recommendation requires operator approval and is recorded for audit.

This repository is built in phases. This document reflects **Phase 7 — the
production operator dashboard** (React + TypeScript + Vite) plus a reference API
that serves the canonical model so the dashboard runs end-to-end.

## Repository layout

```
apps/
  dashboard/        React + TypeScript + Vite operator dashboard (Phase 7)
  api/              Reference WaterTwin API (Phase-7 stand-in for Phase 6)
    app/canonical_water_model.py   Canonical Pydantic model (vendored from Phase 1)
docs/
  OPEN_SOURCE_REGISTER.md  Third-party dependencies + licenses
Dockerfile          Multi-stage build: dashboard -> static, served by the API
docker-compose.yml  One-command stack
```

> Note: Phase 6 (the production API) is not yet merged into `main`, so this phase
> ships a self-contained reference API that vendors the Phase 1 canonical model.
> When Phase 6 lands, the dashboard points at the real backend unchanged — it
> already consumes the canonical `/api/v1` contract.

## Quick start (one command)

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| Dashboard (Simulation Center) | http://localhost:8080 |
| watertwin-api | http://localhost:8000 |
| hydraulic-sim | http://localhost:8100 |

The dashboard proxies `/api` to `watertwin-api`, which calls `hydraulic-sim`.

## Read-only / control boundary

The hydraulic-sim service is a **read-only what-if** engine. It never writes to any
control system: every result carries `provenance="simulated"` and the control
boundary (`control_write_enabled=false`, `operator_approval_required=true`) is
surfaced on `/health` and on every recommendation.

## Tests

```bash
cd services/hydraulic-sim && PYTHONPATH=../../packages pytest
cd services/watertwin-api && PYTHONPATH=../../packages pytest
```

## Open-source licensing

Third-party engines (WNTR / EPANET) are consumed as pinned PyPI packages and
recorded in `docs/licensing/open-source-register.md`. The upstream repositories
are **not** vendored.
Then open <http://localhost:8000>. The dashboard is served from the API static
mount, so a single container provides both the UI and the `/api/v1` surface.

## Local development

Two terminals:

```bash
# 1) Reference API on :8000
cd apps/api
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 2) Dashboard dev server on :5173 (proxies /api -> :8000)
cd apps/dashboard
npm install
npm run dev
```

Open <http://localhost:5173>.

## Dashboard

React 19 + TypeScript + Vite. State via `@tanstack/react-query` (live views poll
every 4 seconds) and a light `zustand` store for selection/scenario. Charts use
ECharts. `maplibre-gl` is wired as a dependency for the geospatial view that
arrives in a later phase.

Pages implemented to full parity in Phase 7:

- **Command Overview (Page 1)** — plant health, production, recovery, permeate
  conductivity, energy + specific energy, HP-pump & membrane status, active
  alarms, active recommendations, service-continuity risk.
- **Process Twin (Page 2)** — selectable 2D stage flow (intake → … → product,
  plus concentrate → ERD → brine). Click a stage or asset to open its twin.
- **Asset Twin (Page 4)** — identity, live state, rated limits, health score with
  contribution breakdown, anomaly score, pump curve (operating point vs BEP),
  "Ask S3M" → recommendation card with ranked causes and approve/reject, and a
  per-asset audit trail.
- **Simulation Center (Page 8)** — stub; simulation services connect in Phases
  8–9.

Remaining pages (3, 5–7, 9–14) are intentionally **not** built in this phase.

### Design constraints honored

- The advisory / no-write **SafetyBoundaryBanner** is always visible.
- Every value carries a **provenance badge** (`synthetic` / `preliminary` /
  `simulated` / `measured`); preliminary/synthetic values are visibly flagged as
  **not validated**.
- **No browser `localStorage`** is used for application data; UI selection state
  is in-memory only.

### Scripts (`apps/dashboard`)

```bash
npm run dev        # dev server
npm run build      # type-check + production build
npm run test       # vitest component tests
npm run test:e2e   # optional Playwright smoke (requires: npx playwright install)
```

## Reference API (`apps/api`)

A FastAPI service that generates provenance-tagged synthetic/preliminary data
conforming to the canonical water model and exposes the `/api/v1` endpoints the
dashboard consumes, including approve/reject that round-trips into an in-memory
audit trail. It is a **Phase-7 stand-in** for the Phase 6 backend and is
replaced when that lands. Key endpoints:

```
GET  /api/v1/control-boundary
GET  /api/v1/overview
GET  /api/v1/assets            GET /api/v1/assets/{id}
GET  /api/v1/streams
GET  /api/v1/health-scores     GET /api/v1/health-scores/{id}
GET  /api/v1/anomaly           GET /api/v1/anomaly/{id}
GET  /api/v1/telemetry/{id}
GET  /api/v1/pump-curve/{id}
GET  /api/v1/recommendations   POST /api/v1/recommendations           (Ask S3M)
POST /api/v1/recommendations/{id}/approve
POST /api/v1/recommendations/{id}/reject
GET  /api/v1/audit
```

## Licensing of dependencies

See [`docs/OPEN_SOURCE_REGISTER.md`](docs/OPEN_SOURCE_REGISTER.md).
**WaterTwin** is an advisory digital-twin *conductor* for water infrastructure
(distribution networks and treatment processes). It ingests operational packets,
routes them through advisory reasoning, produces commander-/operator-ready
briefs and decision cards, and keeps a durable, human-reviewable audit trail.

It is modeled on the **S3M-Core Quad-Engine Orchestration** contract (see
[`docs/architecture/s3m-core-contract.md`](docs/architecture/s3m-core-contract.md))
and adapts that conductor pattern to the water domain.

---

## Product summary

WaterTwin gives water operators a single, auditable place to:

- receive operational packets (sensor/telemetry updates, alerts, decision
  requests, feeds, operator notes) about a water system;
- classify and route them to advisory analysis;
- return structured, human-review-required recommendations and decision cards;
- keep a durable record of *what was recommended, by which component, and why*.

## Architecture principle: **the conductor, not the physics engine**

WaterTwin is the **S3M conductor** for water: it orchestrates, routes, briefs,
and audits. It is **not** the physics/hydraulics/treatment simulator itself.
Simulation engines (Phases 8–9) are separate services that WaterTwin consults;
WaterTwin never becomes the authoritative process controller. See
[`docs/adr/ADR-0001-conductor-not-physics.md`](docs/adr/ADR-0001-conductor-not-physics.md).

## Safety boundary: advisory / read-only, human-in-the-loop

WaterTwin is **advisory and read-only** with respect to plant control. It
**must not** be used for autonomous or closed-loop control of water
infrastructure. Every recommendation is `human_review_required`; a qualified
human operator remains the sole authority for any physical action. The three
boundary fields, and what the platform may and may not do, are specified in
[`docs/security/control-boundaries.md`](docs/security/control-boundaries.md) and
the [`LICENSE`](LICENSE).

## Work-package scope

This repository is the **runnable, tested foundation** for WaterTwin — not the
full 14-page platform. It is built in honest, incremental phases: we ship a
working, tested core first, and defer simulation, production UI, auth, and OT
integration to later phases, documenting what is deferred rather than stubbing
it. See [`docs/adr/ADR-0002-phased-build.md`](docs/adr/ADR-0002-phased-build.md).

---

## Repository layout

```
packages/canonical_water_model/   Shared canonical water asset/data model
services/watertwin-api/           WaterTwin conductor API (FastAPI)
  watertwin/                        Application package
  tests/                            Test suite
  static/                           Static assets
services/hydraulic-sim/           Hydraulic simulation service      (Phase 8)
services/treatment-sim/           Treatment-process simulation      (Phase 9)
apps/dashboard/                   Operator dashboard UI             (Phase 7)
infrastructure/database/          Database schema/migrations (Postgres audit, Phase 5)
docs/                             Architecture, asset model, security, ADRs, etc.
.github/workflows/                CI
```

## Running WaterTwin

> **Placeholder.** The runnable API arrives in a later phase. Once available,
> this section will document environment setup, dependency install, database
> bootstrap, and how to start the WaterTwin API and dashboard locally.

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| 0 | Repo skeleton, S3M-Core contract, architecture decisions & boundaries | **This phase** |
| 1 | Canonical water model (`packages/canonical_water_model`) | Planned |
| 2 | WaterTwin conductor API skeleton (packet submit/status/results) | Planned |
| 3 | Packet routing & advisory brief generation | Planned |
| 4 | Decision cards & operator-ready outputs | Planned |
| 5 | Durable Postgres audit store (closes the S3M-Core in-memory gap) | Planned |
| 6 | Validation & test hardening | Planned |
| 7 | Operator dashboard (`apps/dashboard`) | Planned |
| 8 | Hydraulic simulation service (`services/hydraulic-sim`) | Planned |
| 9 | Treatment-process simulation service (`services/treatment-sim`) | Planned |
| 10 | Security, auth, and OT-integration boundary hardening | Planned |

## License

Proprietary — Abraxas-S3M. Advisory/read-only software; **not** for autonomous
or closed-loop plant control. See [`LICENSE`](LICENSE).
