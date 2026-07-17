# S3M-WaterTwin

Read-only, **advisory** digital twin for a single seawater reverse-osmosis (RO)
treatment train.

> **Architecture principle:** *S3M is the conductor, not the physics engine.*
> Deterministic engineering math lives here in WaterTwin. S3M-Core (a separate
> repository) orchestrates, reasons, and explains via structured packets, and is
> never asked to invent an engineering value that a calculation should produce.

## Safety boundary (non-negotiable)

The platform is advisory-only. These invariants are enforced in code and covered
by tests:

| Invariant                    | Value        |
| ---------------------------- | ------------ |
| `control_mode`               | `"advisory"` |
| `operator_approval_required` | `true`       |
| `control_write_enabled`      | `false`      |

There is **no control-write code path anywhere**. No part of this service can
command a PLC, SCADA, VFD, valve, pump, or dosing system. The platform
recommends; a human decides; everything is audited. The shared control boundary
(`canonical_water_model.ControlBoundary`) defaults to advisory / read-only, and a
CI boundary-guard fails the build if `control_write_enabled = True` ever appears
in `services/` or `packages/`.

## Truthfulness

- All telemetry is **synthetic** (`provenance == "synthetic"`).
- All analytics are **preliminary** (`status == "preliminary"`) and carry a
  disclaimer.
- Output is **never** presented as a validated production prediction, guaranteed
  saving, compliance certification, or autonomous control action.

## Phase 0 scope

This phase establishes the foundation:

- **Deterministic engineering math** (`watertwin.engineering`) — the physics
  engine: osmotic pressure, net driving pressure, water flux, recovery, salt
  rejection/passage, concentration factor, temperature-correction factor,
  specific energy consumption, and a whole-train evaluation.
- **Safety envelope** (`watertwin.safety`) — advisory-only invariants asserted in
  code and tests.
- **Structured JSON logging** (`watertwin.logging_config`).
- **Pydantic v2 schemas** (`watertwin.models`) — synthetic telemetry and
  preliminary analytics packets.
- **Read-only FastAPI service** (`watertwin.api`) with OpenAPI.

## Engineering calculations

All calculations are pure, deterministic, and validate their inputs. They are
idealised engineering approximations suitable for advisory, preliminary
analytics — not laboratory-validated measurements.

| Quantity                     | Model                                              |
| ---------------------------- | -------------------------------------------------- |
| Osmotic pressure             | van't Hoff (NaCl-equivalent), `π = i·c·R·T`        |
| Net driving pressure (NDP)   | `(P_feed − ΔP/2) − P_perm − (π_feed − π_perm)`     |
| Water flux                   | Solution-diffusion, `Jw = A · NDP` (clamped ≥ 0)   |
| Recovery                     | `r = Q_perm / Q_feed`                              |
| Salt passage / rejection     | `SP = C_perm / C_feed`, `R_s = 1 − SP`             |
| Concentration factor         | `(1 − r·(1 − R_s)) / (1 − r)`                       |
| Temperature correction (TCF) | `exp(−k · (T − T_ref))`                            |
| Specific energy (SEC)        | Pump hydraulic power / permeate flow, ERD-aware    |

## Requirements

- Python 3.12
- Dependencies are pinned in `pyproject.toml`; licenses are recorded in
  `THIRD_PARTY_LICENSES.md`.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check .          # lint
pytest                # tests
uvicorn watertwin.api.app:app --reload   # run the API locally
```

Interactive OpenAPI docs are served at `/docs`; the raw schema at `/openapi.json`.

## API

| Method | Path               | Description                                            |
| ------ | ------------------ | ------------------------------------------------------ |
| GET    | `/`                | Service identity and advisory, read-only posture.      |
| GET    | `/health`          | Liveness check.                                        |
| GET    | `/safety`          | The advisory safety envelope in force.                 |
| POST   | `/analytics/train` | Compute preliminary analytics from synthetic telemetry.|

Every response is stamped with `X-Control-Mode: advisory`,
`X-Operator-Approval-Required: true`, and `X-Control-Write-Enabled: false`.

## License

Apache-2.0. See `LICENSE`.
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
- `services/treatment-sim` — **read-only** RO process simulation on the
  open-source **WaterTAP/IDAES** stack (analytical reference model when the
  ipopt solver is not present); baseline, optimize, sensitivity, and
  membrane-degradation what-ifs.
- `apps/dashboard` — React + TypeScript + Vite operator Simulation Center,
  built and served by nginx (which proxies `/api` to `watertwin-api`).
- `packages/watertwin_engineering` — the single canonical physics package
  (osmotic pressure, NDP, flux, recovery, salt rejection/passage, concentration
  factor, TCF, specific energy, whole-train evaluation, and the lumped
  analytical RO reference used to cross-check `treatment-sim`).

## Full persistent stack (Phase 10)

`docker compose up --build` brings up the whole stack **persistently**:

| Service | URL | Notes |
| --- | --- | --- |
| `dashboard` | http://localhost:8080 | Operator Simulation Center (nginx) |
| `watertwin-api` | http://localhost:8000 | Orchestration, recommendations, reports; persists to TimescaleDB |
| `hydraulic-sim` | http://localhost:8100 | EPANET/WNTR hydraulic what-if |
| `treatment-sim` | http://localhost:8081 | WaterTAP/IDAES RO process what-if |
| `timescaledb` | localhost:5432 | Persistent store (`WATERTWIN_DATABASE_URL`) |

The API persists audit events and recommendations to TimescaleDB
(`infrastructure/database/init.sql` creates the telemetry hypertable and the
audit + recommendation tables) and degrades gracefully to in-memory when no
database is configured.

Additional Phase 10 capabilities:

- **Downloadable scenario reports**: `POST /api/v1/reports/scenario/{job_id}`
  returns a Markdown report (baseline vs scenario, impacts, recommended
  response, confidence, provenance, and a mandatory read-only boundary footer).
- **CI safety-boundary guard**: `.github/workflows/ci.yml` fails the build if a
  control-write path (`control_write_enabled = True`) ever appears in
  `services/` or `packages/`, alongside per-service lint/type/test and a
  supply-chain job (CycloneDX SBOMs + `pip-audit` + secret scanning).
- **SBOMs**: `docs/licensing/sbom/*.cdx.json` (regenerate with `make sbom`).
- **Guided demo**: `docs/demonstrations/demo-script.md` (`make scenario-degrade`,
  `make reset`).
- **Identity + RBAC** (commercial hardening #1): Keycloak-backed OIDC login and
  role-based access control (roles `viewer`/`operator`/`engineer`/`admin`/
  `auditor`) across `watertwin-api` and the dashboard. Auth is **enforced by
  default** and bypassable only via the explicit `WATERTWIN_AUTH_DISABLED=true`
  dev-mode env; the identity flows into the audit trail. This does **not** relax
  the advisory/read-only boundary. See
  [`docs/security/identity.md`](docs/security/identity.md).

- **Administration** (commercial hardening): an admin-only surface for
  licensing/entitlement feature-gating by tenant/plan, usage metering
  (facilities, assets, ingest volume) with a billing export, a signed-update
  channel (verify-before-apply; never auto-updates), and in-app support bundles
  (logs + SBOM + config snapshot, **secrets redacted**). These are packaging /
  operational concerns only: **feature gates never touch the advisory/read-only
  safety invariant**, and every response still carries
  `control_write_enabled=false`. Endpoints live under `/api/v1/admin/*`
  (`admin` role) and the dashboard **Administration** page. See
  [`docs/operations/administration.md`](docs/operations/administration.md) and
  [`docs/operations/signed-updates.md`](docs/operations/signed-updates.md).

> Deferred to a later commercial-hardening work package (documented, not built):
> PostGIS spatial features and multi-tenancy.

## Run the stack
Operator-facing digital twin for seawater reverse-osmosis (SWRO) water
treatment. **Advisory, no-write**: the system never writes to plant controls;
every recommendation requires operator approval and is recorded for audit.

The operator dashboard is React + TypeScript + Vite; it consumes the canonical
`/api/v1` contract served by `watertwin-api`.

## Repository layout

```
packages/
  canonical_water_model/   Shared canonical Pydantic model (single source)
  simulation_contracts/    Shared what-if simulation request/result contracts
  watertwin_engineering/   Single canonical physics package (all RO math)
services/
  watertwin-api/           Orchestration API (Simulation Center, recommendations)
  hydraulic-sim/           Read-only EPANET/WNTR hydraulic what-if
  treatment-sim/           Read-only WaterTAP/IDAES RO process what-if
apps/
  dashboard/               React + TypeScript + Vite operator dashboard
docs/ infrastructure/ .github/
docker-compose.yml         One-command stack
```

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
# 1) Orchestration API on :8000
cd services/watertwin-api
pip install -r requirements.txt
PYTHONPATH=../../packages uvicorn app.main:app --reload --port 8000

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

## Orchestration API (`services/watertwin-api`)

A FastAPI service that drives the Simulation Center: it runs baseline-vs-scenario
hydraulic what-ifs, builds provenance-tagged recommendation cards, generates
downloadable scenario reports, and persists audit + recommendations to
TimescaleDB (in-memory fallback). Every response carries the read-only control
boundary. Key endpoints:

```
GET  /health
GET  /api/v1/simulation-center/network
POST /api/v1/simulation-center/run
GET  /api/v1/recommendations   GET /api/v1/recommendations/{id}
POST /api/v1/recommendations/{id}/decision
POST /api/v1/reports/scenario/{job_id}
GET  /api/v1/audit
POST /api/v1/reset
```

## Licensing of dependencies

See [`docs/licensing/open-source-register.md`](docs/licensing/open-source-register.md).
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
