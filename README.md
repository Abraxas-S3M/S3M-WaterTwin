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
