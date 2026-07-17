# Open-Source Register

This register tracks third-party open-source dependencies introduced by the
S3M-WaterTwin project, their pinned versions, and their licenses. Update it
whenever a dependency is added, removed, or upgraded.

## Phase 7 — Operator Dashboard (`apps/dashboard`)

### Runtime dependencies

| Package | Version | License | Purpose |
| --- | --- | --- | --- |
| react | 19.2.7 | MIT | UI library |
| react-dom | 19.2.7 | MIT | React DOM renderer |
| @tanstack/react-query | 5.101.2 | MIT | Server-state / polling data fetching |
| echarts | 6.1.0 | Apache-2.0 | Charting engine (pump curve) |
| echarts-for-react | 3.0.6 | MIT | React wrapper for ECharts |
| zustand | 5.0.14 | MIT | Light global UI state |
| maplibre-gl | 5.24.0 | BSD-3-Clause | Map rendering (integration point; map UI wired in a later phase) |

### Development / build / test dependencies

| Package | Version | License | Purpose |
| --- | --- | --- | --- |
| typescript | 5.9.3 | Apache-2.0 | Type system / compiler |
| vite | 8.1.5 | MIT | Build tool / dev server |
| @vitejs/plugin-react | 6.0.3 | MIT | React plugin for Vite |
| vitest | 4.1.10 | MIT | Unit/component test runner |
| @testing-library/react | 16.3.2 | MIT | Component testing utilities |
| @testing-library/jest-dom | 6.9.1 | MIT | DOM assertions |
| @testing-library/user-event | 14.6.1 | MIT | User interaction simulation |
| jsdom | 29.1.1 | MIT | DOM environment for tests |
| @types/react | 19.2.17 | MIT | React type definitions |
| @types/react-dom | 19.2.3 | MIT | React DOM type definitions |
| @types/node | 22.18.8 | MIT | Node type definitions |
| @playwright/test | 1.61.1 | Apache-2.0 | Optional end-to-end smoke test (optional dependency) |

## Phase 7 — Reference API (`apps/api`)

The reference API is a Phase-7 stand-in for the Phase 6 backend so the dashboard
has a live `/api/v1` surface and `docker compose up` runs as one command.

| Package | Version | License | Purpose |
| --- | --- | --- | --- |
| fastapi | 0.115.6 | MIT | HTTP API framework |
| uvicorn[standard] | 0.34.0 | BSD-3-Clause | ASGI server |
| pydantic | 2.10.4 | MIT | Data models (canonical water model) |
| httpx | 0.28.1 | BSD-3-Clause | Test client dependency (dev/test only) |

### Notes on version pinning

- Dependencies are pinned to specific versions for reproducible builds.
- `typescript` is pinned to `5.9.3` (a well-supported stable line) rather than the
  newest `7.x` native-compiler release, to keep the Vite/Vitest/type-defs
  toolchain reliable for this phase. Revisit when the ecosystem's peer support for
  TypeScript 7 matures.
