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

## Compliance notes

- Both licenses are permissive and compatible with our usage (running the solver
  as a library within a containerized, read-only what-if simulation service).
- No EPANET/WNTR source is vendored; the compiled toolkit is obtained transitively
  through the pinned `wntr` wheel.
- The hydraulic-sim service is **read-only**: it never writes to any control
  system. All results are marked `provenance="simulated"`.
