# S3M-WaterTwin

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
