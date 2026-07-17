# Open-Source Register

This register records third-party open-source components used by S3M-WaterTwin,
their licenses, and how they are consumed. It must be updated **before** a new
open-source dependency is introduced in code.

## How dependencies are consumed

We depend on open-source engines via their published package managers (e.g. PyPI).
We do **not** vendor upstream source repositories into this monorepo. Pinned
versions live in each service's `requirements.txt`.

## Register

| Component | Version | License | SPDX | Consumed via | Used by | Notes |
|-----------|---------|---------|------|--------------|---------|-------|
| WNTR (Water Network Tool for Resilience) | 1.5.0 (pinned) | Revised BSD (3-Clause) | `BSD-3-Clause` | PyPI package `wntr` | `services/hydraulic-sim` | Python hydraulic/water-quality modeling toolkit. Wraps the EPANET solver. Copyright (c) National Technology & Engineering Solutions of Sandia, LLC (NTESS) and the U.S. Environmental Protection Agency (US EPA). |
| EPANET toolkit | Bundled with WNTR 1.5.0 (EPANET 2.2 engine) | See notes | `MIT` / Public Domain | Bundled inside the `wntr` wheel (compiled toolkit) — not vendored separately | `services/hydraulic-sim` (indirectly, through WNTR) | EPANET is hydraulic/water-quality solver software originally authored by the U.S. EPA and released to the public domain. The maintained toolkit distributed by the Open Water Analytics (OWA) community (`epanet`/`owa-epanet`) is provided under the MIT License. WNTR ships a compiled EPANET toolkit inside its wheel; we do not build or vendor EPANET ourselves. |

### WNTR — Revised BSD (3-Clause) summary

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met: (1) redistributions
of source code retain the copyright notice, this list of conditions, and the
disclaimer; (2) redistributions in binary form reproduce the same in
documentation and/or other materials; (3) neither the names of the copyright
holders nor the names of contributors may be used to endorse or promote products
derived from this software without specific prior written permission. Provided
"as is" without warranty.

Upstream project: https://github.com/USEPA/WNTR — License file:
https://github.com/USEPA/WNTR/blob/main/LICENSE.md

### EPANET summary

EPANET is public-domain software produced by the U.S. EPA. The Open Water
Analytics maintained engine (used by the wider ecosystem, including WNTR's
bundled toolkit) is distributed under the MIT License, which permits use, copy,
modification, and distribution provided the copyright and permission notice are
retained. Provided "as is" without warranty.

Upstream project: https://github.com/OpenWaterAnalytics/EPANET

## Direct dependency register (reconciled against SBOMs)

The table below records the primary **direct** dependencies of each service and
the persistence/UI tiers. It is reconciled against the machine-generated
CycloneDX SBOMs under `docs/licensing/sbom/` (see next section). Transitive
components are enumerated in full inside those SBOMs.

| Component | Version | License (SPDX) | Consumed via | Used by |
|-----------|---------|----------------|--------------|---------|
| fastapi | 0.115.x / 0.139.x | `MIT` | PyPI | all API services |
| uvicorn[standard] | 0.34.x / 0.51.x | `BSD-3-Clause` | PyPI | all API services |
| pydantic | 2.10–2.13 | `MIT` | PyPI | all services + shared packages |
| httpx | 0.28.1 | `BSD-3-Clause` | PyPI | api clients / tests |
| psycopg[binary] | 3.2.3 | `LGPL-3.0-or-later` | PyPI | `services/watertwin-api` (DB driver) |
| asyncua | 1.1.6 | `LGPL-3.0-only` | PyPI | `services/watertwin-api` (read-only OPC UA **client** connector) |
| pymodbus | 3.7.4 | `BSD-3-Clause` | PyPI | `services/watertwin-api` (read-only Modbus connector) |
| numpy | 2.4.4 | `BSD-3-Clause` | PyPI | `services/hydraulic-sim`, `treatment-sim` |
| scipy | 1.18.0 | `BSD-3-Clause` | PyPI | `services/hydraulic-sim`, `services/watertwin-api`, `packages/watertwin_engineering` |
| pandas | 3.0.3 | `BSD-3-Clause` | PyPI | `services/hydraulic-sim` |
| networkx | 3.6.1 | `BSD-3-Clause` | PyPI | `services/hydraulic-sim` |
| wntr | 1.5.0 | `BSD-3-Clause` | PyPI | `services/hydraulic-sim` (see WNTR/EPANET above) |
| watertap | 1.7.0 | `BSD-3-Clause` (DOE) | PyPI | `services/treatment-sim` |
| idaes-pse | 2.12.0 | `BSD-3-Clause` (IDAES/DOE) | PyPI | `services/treatment-sim` |
| pyomo | 6.10.1 | `BSD-3-Clause` | PyPI | `services/treatment-sim` |
| TimescaleDB (community) | 2.17.2 (pg16) | `Apache-2.0` | Docker image `timescale/timescaledb` | persistence tier |
| PostgreSQL | 16 | `PostgreSQL` | bundled in TimescaleDB image | persistence tier |
| nginx | 1.27-alpine | `BSD-2-Clause` | Docker image `nginx` | `dashboard` static server |
| React / Vite / TypeScript toolchain | see `sbom-dashboard.cdx.json` | mostly `MIT` / `ISC` | npm | `apps/dashboard` |

> `psycopg` (v3) is LGPL-3.0-or-later. It is consumed **unmodified** as a
> dynamically-linked library via its published wheel; we do not modify or
> statically embed it, which is compatible with LGPL terms.

> `asyncua` is LGPL-3.0. Like `psycopg`, it is consumed **unmodified** as a
> dynamically-linked library via its published PyPI wheel (dynamic use only); we
> do not modify or statically embed it, which is compatible with LGPL terms. It
> is used exclusively as a read-only OPC UA **client** in `app/sources/opcua.py`
> — no node-write / attribute-set call exists (enforced by
> `tests/test_ot_sources.py::test_sources_package_has_no_write_path`).

> `pymodbus` is BSD-3-Clause (permissive). It is used in `app/sources/modbus.py`
> with **read function codes only** (read coils / discrete inputs / holding
> registers / input registers); no write function code appears in the code
> (enforced by the same read-only boundary-guard test).

## Software Bill of Materials (SBOM)

Machine-readable CycloneDX SBOMs are generated for every deployable tier and
stored under `docs/licensing/sbom/`:

| SBOM | Scope | Generator |
|------|-------|-----------|
| `sbom-watertwin-api.cdx.json` | watertwin-api Python deps | `cyclonedx-py` |
| `sbom-hydraulic-sim.cdx.json` | hydraulic-sim Python deps | `cyclonedx-py` |
| `sbom-treatment-sim.cdx.json` | treatment-sim Python deps | `cyclonedx-py` |
| `sbom-dashboard.cdx.json` | dashboard (npm) deps | `cyclonedx-npm` |

Regenerate them with:

```bash
make sbom          # all of the above
```

or manually:

```bash
# Python services (CycloneDX)
python -m cyclonedx_py requirements services/watertwin-api/requirements.txt \
    -o docs/licensing/sbom/sbom-watertwin-api.cdx.json
python -m cyclonedx_py requirements services/hydraulic-sim/requirements.txt \
    -o docs/licensing/sbom/sbom-hydraulic-sim.cdx.json
python -m cyclonedx_py requirements services/treatment-sim/requirements.txt \
    -o docs/licensing/sbom/sbom-treatment-sim.cdx.json

# Dashboard (npm)
cd apps/dashboard && npx @cyclonedx/cyclonedx-npm --package-lock-only \
    --output-format JSON --output-file ../../docs/licensing/sbom/sbom-dashboard.cdx.json
```

The CI `security` job regenerates the SBOMs on every run and runs dependency
(`pip-audit`) and secret scanning, so drift between the register, the SBOMs, and
the pinned `requirements.txt` files is caught automatically.

## Compliance notes

- Both licenses are permissive and compatible with our usage (running the solver
  as a library within a containerized, read-only what-if simulation service).
- No EPANET/WNTR source is vendored; the compiled toolkit is obtained transitively
  through the pinned `wntr` wheel.
- The hydraulic-sim service is **read-only**: it never writes to any control
  system. All results are marked `provenance="simulated"`.
