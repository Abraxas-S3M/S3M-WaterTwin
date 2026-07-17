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
recommends; a human decides; everything is audited. The safety envelope
(`watertwin.safety.SafetyEnvelope`) is *fail-closed*: it cannot be constructed in
any non-advisory state.

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
