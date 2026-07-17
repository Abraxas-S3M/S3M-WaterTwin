# ADR-0001: WaterTwin is the S3M conductor, not the physics engine

- **Status:** Accepted
- **Date:** 2026-07-17
- **Phase:** 0 (bootstrap)

## Context

S3M-Core's Quad-Engine layer is an **orchestration conductor**: it receives
operational packets, classifies and routes them to advisory engines, and returns
structured, human-review-required briefs and decision cards. It deliberately does
**not** perform the underlying domain computation itself — routing is
deterministic and offline, and outputs are recommendations, never actions
(see [`docs/architecture/s3m-core-contract.md`](../architecture/s3m-core-contract.md)).

WaterTwin adapts this pattern to the water domain. A water platform naturally
tempts scope creep toward *being* the hydraulic/treatment simulator and, from
there, toward *controlling* the plant. We need an explicit, durable decision
about what WaterTwin is and is not.

## Decision

**WaterTwin is the conductor, not the physics engine.**

1. WaterTwin's core responsibility is **orchestration**: ingest packets, route
   them, generate advisory briefs and decision cards, and maintain a durable,
   human-reviewable audit trail.
2. **Simulation is separate.** Hydraulic simulation (Phase 8,
   `services/hydraulic-sim`) and treatment-process simulation (Phase 9,
   `services/treatment-sim`) are distinct services that WaterTwin *consults* as
   advisory inputs. WaterTwin does not embed and does not become the
   authoritative physics model.
3. **Read-only / advisory boundary.** WaterTwin is advisory and read-only with
   respect to plant control. It never actuates equipment and never operates in a
   closed loop. Every output is `human_review_required`; a qualified human
   operator is the sole authority for any physical action. The concrete boundary
   is specified in
   [`docs/security/control-boundaries.md`](../security/control-boundaries.md).

## Consequences

- The conductor and the simulators can evolve, scale, and be validated
  independently; a simulator failure degrades WaterTwin to honest "engine
  unavailable" rather than producing unsafe control output.
- WaterTwin's API surface mirrors the S3M-Core contract (packet submit / status /
  engines / results / audit) rather than a control surface.
- There is a clear, auditable line between *advice* (what WaterTwin produces) and
  *action* (what a human authorizes and an external, separately-governed control
  system performs). No WaterTwin code path may cross that line.
- Any future request to add direct control or closed-loop behavior must be
  rejected or handled by a separate, explicitly governed system — it is
  out of scope for WaterTwin by design.
