# S3M-WaterTwin

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
