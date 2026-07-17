# treatment-sim

Read-only reverse-osmosis (RO) **process-simulation** service for S3M-WaterTwin,
built on the open-source **WaterTAP / IDAES / Pyomo** stack (US DOE funded,
BSD-style licensed). It answers *what-if* and *optimization* questions only.

> **Boundary:** This service is strictly advisory. It performs no closed-loop
> control, never writes to any control system, and always tags results
> `provenance="simulated"`, `status="preliminary"`. Simulated output is never
> presented as measured or validated.

## Engine

- Prefers the **WaterTAP 0-D RO flowsheet** solved with `ipopt` when the stack
  and solver are available (they are installed in the container — see
  `Dockerfile`; the solver is **never** added to the API image).
- Falls back to an **analytical** RO model (`app/ro_model.py`, a discretized
  multi-segment solution-diffusion solve) when the solver is unavailable.
- The analytical model is cross-checked against `watertwin/calculations.py`
  (an independent lumped-element implementation of the same physics). The two
  must agree within tolerance; divergence is treated as a bug signal.

## Endpoints (async jobs)

| Method & path | Purpose |
| --- | --- |
| `POST /api/v1/process/simulate` | Baseline RO: recovery, specific energy, permeate TDS, salt rejection. |
| `POST /api/v1/process/optimize` | Minimize specific energy s.t. recovery + product-quality limits. |
| `POST /api/v1/process/sensitivity` | Sweep feed salinity / temperature / pressure. |
| `POST /api/v1/process/membrane-degradation` | Apply A/B permeability decline; report flow/quality/energy impact. |
| `GET  /api/v1/process/jobs/{job_id}` | Poll an async job. |
| `GET  /health` | Health + control-boundary fields. |

Simulation endpoints return `202 Accepted` with a queued job; poll the job
endpoint until `state == "succeeded"`.

### Example

```bash
curl -s -X POST http://localhost:8081/api/v1/process/simulate \
  -H 'content-type: application/json' \
  -d '{"feed":{"flow_m3h":100,"tds_mg_l":35000,"temperature_c":25,"pressure_bar":60},
       "membrane":{"area_m2":1200}}'
# -> {"job_id":"...","state":"queued",...}
curl -s http://localhost:8081/api/v1/process/jobs/<job_id>
```

## Run

```bash
# From the repository root:
docker compose up --build treatment-sim
# Service on http://localhost:8081 ; health at /health.
```

## Tests

```bash
cd services/treatment-sim
python -m pytest
```

Tests run against the analytical engine (no solver required) and cover baseline
plausibility, sensitivity monotonicity, membrane degradation, and agreement with
`watertwin/calculations.py`.

## Contracts

Request/result models live in `packages/simulation_contracts` and are shared
with the API layer (`watertwin/treatment_sim_client.py`,
`watertwin/simulation_center.py`).
