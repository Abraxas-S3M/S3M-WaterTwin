# hydraulic-sim

Read-only **what-if** hydraulic simulation service for S3M-WaterTwin, built on the
open-source **EPANET** engine via **WNTR** (Water Network Tool for Resilience).

> This service never writes to any control system. Every result is tagged
> `provenance="simulated"`, `status="preliminary"`, and carries the read-only
> control-boundary (`control_write_enabled=false`). See
> `docs/licensing/open-source-register.md` for licensing.

## Network model

`models/ro-handoff.inp` is a standard EPANET input file representing the
RO-TRAIN-001 **product-water storage / pumping / pipeline handoff**:

- `R-PERM` — remineralized permeate / finished-water buffer (source)
- `PU-PROD-1`, `PU-PROD-2` — two parallel product-water transfer pumps
- `T-PROD` — elevated product-water storage tank
- `CV-HANDOFF` — metered handoff control valve
- `J-D1`..`J-D3` — distribution handoff demand nodes

The same network is reproduced in code by
`app/network.py::build_ro_handoff_network` (used to regenerate the `.inp` and as a
fallback). It uses pressure-dependent demand (required pressure 25 m).

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/hydraulics/simulate` | Baseline (pressures, flows, tank levels) |
| POST | `/api/v1/hydraulics/pump-outage` | Remove a pump, report impact |
| POST | `/api/v1/hydraulics/valve-closure` | Close/throttle a valve |
| POST | `/api/v1/hydraulics/demand-change` | Scale or override demands |
| POST | `/api/v1/hydraulics/leak` | Add an emitter leak; localize by residual |
| GET | `/api/v1/hydraulics/jobs/{job_id}` | Poll async job + result |
| GET | `/api/v1/hydraulics/network` | Describe network elements |
| GET | `/health` | Liveness + control-boundary fields |

All simulate endpoints are **async jobs**: they return `202` with a `job_id`;
poll the job endpoint for the persisted `SimulationResult`.

## Run locally

```bash
pip install -r requirements.txt
PYTHONPATH=../../packages uvicorn app.main:app --port 8100
```

## Regenerate the .inp model

```bash
PYTHONPATH=../../packages python -m app.network
```

## Test

```bash
PYTHONPATH=../../packages pytest
```
