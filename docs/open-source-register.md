# Open-Source Register

This register records every third-party open-source component introduced into
S3M-WaterTwin, together with its license and how it is consumed. Entries must be
added **before** the dependency is used in code.

Guiding rules:

- Prefer permissive, well-maintained, ideally government/lab-funded stacks.
- Record the exact pinned version and the license family.
- Do **not** vendor upstream repositories; consume published packages only.
- Solvers and other heavyweight native binaries are installed in the specific
  service container that needs them, never in the shared API image.

## Phase 9 — RO process simulation (`services/treatment-sim`)

The read-only reverse-osmosis process-simulation service is built on the
open-source WaterTAP / IDAES / Pyomo stack (a US Department of Energy funded
ecosystem). All three are permissive BSD-style licenses compatible with this
project.

| Package | Pinned version | License | Source / steward | How consumed |
| --- | --- | --- | --- | --- |
| `watertap` | 1.7.0 | BSD-3-Clause style (NAWI / DOE) | National Alliance for Water Innovation (watertap-org/watertap) | PyPI wheel only, imported by `services/treatment-sim/app/watertap_engine.py`. Repo **not** vendored. |
| `idaes-pse` | 2.12.0 | BSD-3-Clause (IDAES / DOE) | Institute for the Design of Advanced Energy Systems (IDAES/idaes-pse) | PyPI wheel; transitive/direct dependency of WaterTAP flowsheets. |
| `pyomo` | 6.10.1 | BSD-3-Clause (Sandia National Labs / DOE) | Pyomo project (Pyomo/pyomo) | PyPI wheel; algebraic modeling layer under IDAES/WaterTAP. |
| `ipopt` (solver) | via `idaes get-extensions` / conda-forge in container | EPL-2.0 (COIN-OR) | COIN-OR Ipopt | Installed **only** in the `treatment-sim` Dockerfile as the NLP solver. Never installed in the API image. |

### License notes

- WaterTAP and IDAES both distribute a modified BSD-3-Clause license (the
  canonical text ships in each upstream repository's `LICENSE.md`). They are
  produced under US DOE funding and are freely redistributable.
- Pyomo is released under a BSD-3-Clause license by Sandia National
  Laboratories.
- Ipopt is licensed under the Eclipse Public License 2.0 (EPL-2.0). It is a
  standalone solver binary invoked at runtime and is confined to the
  `treatment-sim` container; it is not linked into or bundled with any other
  service image.

### Runtime / service dependencies (already permissive)

| Package | Pinned version | License |
| --- | --- | --- |
| `fastapi` | 0.115.14 | MIT |
| `uvicorn` | 0.34.0 | BSD-3-Clause |
| `pydantic` | 2.11.7 | MIT |
| `httpx` | 0.28.1 | BSD-3-Clause |
