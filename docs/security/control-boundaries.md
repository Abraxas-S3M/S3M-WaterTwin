# WaterTwin Control Boundaries

WaterTwin is an **advisory, read-only decision-support conductor**. This document
defines the hard boundary between *advice* (what WaterTwin produces) and *action*
(what a qualified human authorizes and a separate, governed system performs).
This boundary is normative and inherited from the S3M-Core safety doctrine (see
[`docs/architecture/s3m-core-contract.md`](../architecture/s3m-core-contract.md))
and [ADR-0001](../adr/ADR-0001-conductor-not-physics.md). It is also codified in
the [`LICENSE`](../../LICENSE).

## The three boundary fields

Every WaterTwin result carries three fields that make the safety posture explicit
and machine-checkable. They are adopted from the S3M-Core contract:

1. **`human_review_required`** *(default `true`)* — present on every result and,
   as a per-card `status` default, on every decision card
   (`status = "human_review_required"`). No result and no card is ever
   auto-approved. A qualified human must review before anything is acted upon.

2. **`autonomous_action_enabled`** *(always `false`)* — reported by the
   orchestrator status. WaterTwin has no code path that enables autonomous
   action. This is a fixed invariant, not a configurable toggle.

3. **`engine_status`** *(`live_local` | `placeholder` | `unavailable`)* —
   reported per advisory engine so an operator can always see whether an output
   came from a live model/simulation, a deterministic placeholder, or an
   unavailable engine. Provenance is never hidden; a placeholder is never
   presented as a live assessment.

## What the platform MAY do

- Ingest operational packets (telemetry/sensor updates, alerts, decision
  requests, feeds, operator notes) about a water system.
- Classify and route packets to advisory reasoning/analysis (deterministic,
  offline routing).
- Produce **recommendations, briefs, summaries, and decision cards** for human
  review.
- Consult separate simulation services (hydraulic, treatment) as **advisory
  inputs** and report their status and provenance.
- Maintain a durable, append-only, human-reviewable **audit trail** of what was
  recommended, by which component, and why.

## What the platform MUST NOT do

- **No actuation.** It must not command, actuate, or control pumps, valves,
  dosing systems, SCADA/PLC/ICS equipment, or any operational technology (OT) or
  physical process — directly or indirectly.
- **No closed-loop / autonomous control.** It must not operate in any
  autonomous, unattended, or closed-loop control mode.
- **No authority substitution.** It must not be treated as a substitute for a
  qualified human operator, established operating procedures, regulatory
  controls, or independent safety systems.
- **No secret/credential surfacing.** It must not expose model paths,
  credentials, or vault keys through its API; only advisory outputs are returned.

## Human-in-the-loop

A qualified human operator is the **sole authority** for any physical action.
WaterTwin's role ends at producing a reviewed-and-reviewable recommendation. The
transition from recommendation to physical action happens **outside** WaterTwin,
through a separate, explicitly governed control system operated by that human.
The `human_review_required` field enforces this contractually on every output.

## Provenance

Every advisory output is attributable:

- **Engine/source provenance** via `engine_status` (`live_local` /
  `placeholder` / `unavailable`) — operators always know whether an assessment
  is live or a stand-in.
- **Routing provenance** — the routing decision records the primary/supporting
  components and a plain-language `reason` for the audit trail.
- **Audit provenance** — each audit entry records the action, timestamp, and
  details. WaterTwin will persist this durably in Postgres (Phase 5), closing the
  gap that the upstream S3M-Core audit log is in-memory only.

## No control path and no inbound dependency (edge / one-way posture)

Beyond being advisory-only, WaterTwin's edge deployment posture guarantees a
**directional** property: the **gateway has no control path into the platform,
and the platform has no inbound dependency on — or connection into — the OT
zone.** This is what makes the platform safe to run next to a live plant and is
the basis for the XiiD-ready / data-diode topology in
[`docs/deployment/edge-xiid-reference.md`](../deployment/edge-xiid-reference.md).

The following are asserted as normative invariants:

- **The edge gateway has no control path.** The gateway only *reads* OT
  telemetry and *pushes* it toward the platform. It exposes no command, no
  actuation, and no write path into either the OT process or the platform's
  decision-making. It cannot cause the platform to take an action, and it cannot
  be used as a channel to actuate OT.
- **The platform never initiates a connection toward OT.** Under the
  `one_way_diode` deployment profile the platform is structurally incapable of
  opening a connection into the OT zone. Every platform→OT request code path
  (OPC UA / Modbus / historian REST or SQL pulls) is **disabled at startup,
  fail-closed** (see `services/watertwin-api/app/deployment.py`); the service
  refuses to start rather than silently degrade, and an unknown profile value
  fails closed to the most restrictive posture.
- **No inbound dependency.** The OT side exposes **no public IP and no inbound
  listening ports** to the platform. The platform's correct operation does not
  depend on reaching back into the OT zone: telemetry arrives only via the edge
  gateway's **outbound** mTLS push (SealedTunnel / XOTC style). If the gateway is
  offline the platform simply has no new telemetry — it never tries to "call
  home" into OT.
- **Single, authenticated, one-way conduit.** Exactly one
  [IEC 62443](https://www.isa.org/standards-and-publications/isa-standards/isa-iec-62443-series-of-standards)
  conduit crosses the OT zone boundary: the gateway's outbound tunnel. It is
  mutually authenticated (mTLS) and grants process-to-process reachability only,
  never subnet-to-subnet routing.

These application-layer invariants are reinforced at the network layer by the
manifests in [`infrastructure/network-policy/`](../../infrastructure/network-policy/)
(default-deny + egress allowlists that exclude OT CIDRs/protocols) and
[`infrastructure/gateway/`](../../infrastructure/gateway/) (outbound-only + mTLS).
The fail-closed guarantee is proven by
[`services/watertwin-api/tests/test_deployment_profile.py`](../../services/watertwin-api/tests/test_deployment_profile.py).

## Reversibility

Because WaterTwin never takes physical action, its outputs are inherently
reversible: producing, revising, or discarding a recommendation has no
side-effects on the physical plant. The only durable side-effect is the
append-only audit record, which is retained deliberately for oversight and
reconstruction. Any *physical* change remains fully under human control and
subject to the plant's own separate, reversible operating procedures — never
initiated or locked in by WaterTwin.
