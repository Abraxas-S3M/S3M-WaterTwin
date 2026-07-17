# ADR-0002: Ship a runnable, tested foundation first (phased build)

- **Status:** Accepted
- **Date:** 2026-07-17
- **Phase:** 0 (bootstrap)

## Context

The full WaterTwin vision is a large, multi-service platform (conductor API,
canonical model, durable audit, dashboard, hydraulic and treatment simulation,
auth, and OT-integration boundaries). Attempting to deliver all of it at once
tends to produce broad but shallow scaffolding: many stubbed modules that look
complete but neither run nor are tested, hiding real risk.

## Decision

**We build in honest, incremental phases and ship a runnable, tested foundation
first.**

1. **Runnable and tested over broad-but-fake.** Each phase delivers something
   that actually runs and is covered by tests, rather than a wide field of
   empty stubs. Correctness and provenance are verified against the real
   S3M-Core contract, not guessed.
2. **Defer deliberately, document honestly.** Simulation
   (`services/hydraulic-sim`, `services/treatment-sim`), the production operator
   UI (`apps/dashboard`), authentication, and OT integration are **deferred to
   later phases**. Deferred capabilities are documented as deferred (in this ADR
   and the README roadmap) rather than faked with non-functional placeholders.
3. **Phase 0 scope.** This phase establishes only: the repository skeleton, an
   accurate S3M-Core contract document derived from the real upstream code, and
   the foundational architecture/security decisions. **No business logic,
   analytics, calculations, or API code** is added in Phase 0.
4. **Phased roadmap.** The phase sequence (0–10) is tracked in the README
   roadmap table and is the source of truth for what is in scope when.

## Consequences

- Reviewers and stakeholders can trust that anything present in the repo is real:
  either it runs and is tested, or it is explicitly documented as not-yet-built.
- Empty directories carry `.gitkeep` placeholders to establish structure without
  implying functionality.
- The durable Postgres audit store — which closes the known gap that S3M-Core's
  audit log is in-memory only — is explicitly scheduled (Phase 5) rather than
  hand-waved.
- Progress is measured by working, tested increments per phase, not by lines of
  scaffolding.
