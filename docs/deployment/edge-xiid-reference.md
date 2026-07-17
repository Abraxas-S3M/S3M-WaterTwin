# Edge / XiiD-Ready Reference Topology

This document is a **reference deployment topology** for running S3M-WaterTwin
next to a live operational-technology (OT) plant while preserving WaterTwin's
advisory, read-only posture *and* a strict one-way flow of information out of the
OT zone. It describes how an **edge gateway** connects the OT side to the
WaterTwin platform **strictly outbound**, how that maps onto an
[IEC 62443](https://www.isa.org/standards-and-publications/isa-standards/isa-iec-62443-series-of-standards)
zone/conduit model, and where an [XiiD](https://xiid.com/) mesh connector /
**XOTC** (Xiid OpenTunnel Connector) would terminate.

> **Scope note — no crypto is reimplemented here.** WaterTwin does **not**
> reimplement Xiid's Zero-Knowledge Network (ZKN) cryptography, key exchange, or
> tunnel transport. Those primitives are provided by Xiid's own components
> (SealedTunnel / XOTC / mesh connector) and are consumed as a black box. This
> document describes only how WaterTwin is *positioned* to be XiiD-ready:
> outbound-only, mTLS-terminated, process-to-process, fail-closed. All ZKN key
> material and tunnel establishment stay inside the Xiid components.

Related material:

- Directional guarantee in code: [`services/watertwin-api/app/deployment.py`](../../services/watertwin-api/app/deployment.py)
  (`DEPLOYMENT_PROFILE`).
- Control boundary / no-control-path assertion: [`docs/security/control-boundaries.md`](../security/control-boundaries.md).
- Network policy + gateway config: [`infrastructure/network-policy/`](../../infrastructure/network-policy/)
  and [`infrastructure/gateway/`](../../infrastructure/gateway/).

---

## Design goals

1. **Outbound-only from the OT side.** The edge gateway *initiates* every
   connection **toward** the platform. Nothing on the OT side listens for, or
   depends on, an inbound connection from the platform.
2. **No public IP / no inbound ports on the OT side.** The OT network exposes no
   routable address and opens no listening port to the platform or the internet.
   The only egress is the gateway's outbound tunnel.
3. **mTLS between gateway and API.** The gateway and the WaterTwin API mutually
   authenticate with X.509 client/server certificates; neither trusts an
   unauthenticated peer.
4. **Process-to-process access only.** The tunnel exposes exactly one upstream
   process (the WaterTwin ingestion endpoint) to exactly one downstream process
   (the gateway). No network-level lateral reachability is granted; there is no
   "flat network" between zones.
5. **One-way / data-diode profile.** In the strictest profile the gateway is
   **push-only** and the platform is structurally incapable of initiating a
   request back into the OT zone. This is enforced at the network layer (diode /
   one-way conduit) **and** in the application (`DEPLOYMENT_PROFILE=one_way_diode`,
   fail-closed — see below).

---

## Reference topology

```
        OT ZONE (Purdue L0-L3)                 :  CONDUIT            :   ENTERPRISE / CLOUD ZONE (L4/L5)
                                               :  (one-way)         :
  +-------------------+   read-only            :                    :   +-------------------------+
  | PLC / RTU / SCADA |  (OPC UA / Modbus /    :                    :   |   WaterTwin platform    |
  | Sensors, historian|   historian export)    :                    :   |                         |
  +---------+---------+                        :                    :   |  +-------------------+  |
            |  (L0-L2 field/control bus)       :                    :   |  |  watertwin-api    |  |
            v                                  :                    :   |  |  (ingestion only) |  |
  +-------------------+                        :   outbound-only    :   |  +----^--------------+  |
  |   EDGE GATEWAY    |====== mTLS tunnel =====:===== push ========>:====== | (mTLS server)      |
  |  (XOTC / mesh     |   (Xiid SealedTunnel,  :   NEVER inbound    :   |     |                   |
  |   connector       |    ZKN transport)      :                    :   |  +--v----------------+  |
  |   terminates here)|                        :                    :   |  | hydraulic/treat.  |  |
  +-------------------+                        :                    :   |  | sim, dashboard    |  |
   - no public IP                              :                    :   |  +-------------------+  |
   - no inbound ports                          :                    :   +-------------------------+
   - egress = tunnel only                      :                    :    - no route INTO the OT zone
```

Key properties of the diagram:

- The arrow between the gateway and `watertwin-api` points **one way**
  (OT → platform). There is no return arrow that lets the platform originate a
  request into the OT zone.
- The **edge gateway is the only element with any egress**, and its egress is a
  single outbound tunnel to the platform ingestion endpoint.
- The platform's ingestion endpoint is a **server** for the mTLS tunnel; it is
  never a **client** of anything inside the OT zone.

---

## IEC 62443 zone / conduit sketch

| Element | 62443 role | Purdue level(s) | Notes |
|---------|------------|-----------------|-------|
| PLC / RTU / SCADA / sensors / plant historian | **OT zone** (highest SL-T) | L0–L2 (field/control), L3 (site ops) | No public IP, no inbound ports from higher zones. |
| Edge gateway (XOTC / mesh connector) | **Zone boundary device** on the OT zone edge | L3 / L3.5 (DMZ-side) | Reads OT read-only; terminates the ZKN tunnel; only outbound egress. |
| mTLS tunnel gateway → API | **Conduit** (single, authenticated, one-way) | crosses L3.5 → L4 | Mutually authenticated; carries telemetry push only. |
| `watertwin-api` ingestion | **Enterprise/cloud zone** endpoint | L4/L5 | mTLS server; advisory/read-only; never a control-write path. |
| hydraulic-sim / treatment-sim / dashboard | Enterprise/cloud zone | L4/L5 | No path back into the OT zone. |

Conduit rules asserted by this topology:

1. **Exactly one conduit** crosses the OT zone boundary: the gateway's outbound
   tunnel. There is no second, inbound conduit.
2. The conduit is **authenticated in both directions** (mTLS) but **carries data
   in one direction** (OT → platform) under the one-way profile.
3. The conduit grants **process-to-process** reachability only (gateway process
   ↔ ingestion process), never subnet-to-subnet routing.
4. A **data diode** (or equivalent one-way appliance) MAY be placed in the
   conduit so the one-way property is enforced by hardware, not only by policy.

---

## Where XiiD terminates

- The **XOTC / Xiid mesh connector runs on (or immediately beside) the edge
  gateway inside the OT zone edge (L3/L3.5).** It establishes the
  **SealedTunnel** *outbound* to the Xiid mesh; the ZKN handshake and transport
  are handled entirely by Xiid.
- On the platform side, the tunnel terminates at a Xiid mesh endpoint that
  presents the gateway as a local, mutually-authenticated peer to
  `watertwin-api`. From WaterTwin's perspective this is just an **mTLS client**
  pushing telemetry to the ingestion endpoint.
- **WaterTwin never sees, stores, or reimplements ZKN key material.** It relies
  on the Xiid components for tunnel identity/crypto and layers its own mTLS +
  RBAC + fail-closed profile on top. WaterTwin's responsibility begins at the
  ingestion endpoint (authenticate the peer, accept a telemetry push, normalize
  it read-only) and ends there.

Because the SealedTunnel is outbound-only and the platform holds no route into
the OT zone, the XiiD termination model and WaterTwin's `one_way_diode` profile
reinforce the same guarantee at two layers (network transport + application).

---

## Deployment profiles

WaterTwin exposes the directional posture as a first-class config flag,
`DEPLOYMENT_PROFILE` (see [`app/config.py`](../../services/watertwin-api/app/config.py)
and [`app/deployment.py`](../../services/watertwin-api/app/deployment.py)):

| Profile | Meaning | Platform → OT connection | Allowed telemetry sources |
|---------|---------|--------------------------|---------------------------|
| `standard` | Platform may pull telemetry from a real OT feed. Reads are still strictly read-only, but the **platform initiates** the connection toward OT. | Permitted (read-only) | `synthetic`, `opcua`, `modbus`, `historian` (csv/rest/sql) |
| `one_way_diode` | One-way / data-diode topology. The edge gateway **pushes** telemetry; the platform **never** initiates a connection toward OT. | **Disabled at startup (fail-closed)** | `synthetic`, gateway-pushed / `historian:csv` file feeds only |

### Fail-closed behaviour under `one_way_diode`

- At **startup** the app validates the profile: if the configured telemetry
  source is a platform-initiated OT pull (`opcua`, `modbus`, or `historian` with
  `rest`/`sql` access), the service **refuses to start** and raises
  `OneWayDiodeViolation`. It does **not** silently downgrade to a synthetic feed.
- The **telemetry-source resolver** refuses to build a platform-initiated OT
  source under this profile (same fail-closed error), so no OPC UA / Modbus /
  historian-REST/SQL client is ever constructed.
- An **unknown / mistyped** `DEPLOYMENT_PROFILE` value fails closed to
  `one_way_diode` (the most restrictive posture), so a typo can never
  accidentally open a platform→OT path. (An empty/unset value is the
  backward-compatible `standard` default.)
- `/health` reports `deployment_profile` and `platform_to_ot_enabled` so the
  active posture is observable.

This is proven by
[`tests/test_deployment_profile.py`](../../services/watertwin-api/tests/test_deployment_profile.py),
which asserts that under `one_way_diode` every platform→OT source is refused at
both resolution and startup, while `synthetic` / `historian:csv` feeds start
normally.

### Enabling the one-way profile

```bash
# Platform side (watertwin-api): refuse any platform->OT request path.
export DEPLOYMENT_PROFILE=one_way_diode
export OT_SOURCE=synthetic          # or a gateway-pushed historian:csv drop
```

Combine this with the network policy in
[`infrastructure/network-policy/`](../../infrastructure/network-policy/) (egress
allowlist that denies the API any route into the OT zone) and the gateway config
in [`infrastructure/gateway/`](../../infrastructure/gateway/) (outbound-only +
mTLS) so the one-way guarantee holds at the network layer as well as in the app.

---

## Checklist for an XiiD-ready edge deployment

- [ ] OT zone has **no public IP** and **no inbound listening ports** exposed to
      the platform.
- [ ] Edge gateway egress is limited to the **single outbound tunnel** (XOTC /
      SealedTunnel) — see the egress allowlist manifest.
- [ ] **mTLS** enforced on the gateway↔API conduit (client + server certs, no
      anonymous peers).
- [ ] Conduit grants **process-to-process** reachability only (no subnet
      routing between zones).
- [ ] `DEPLOYMENT_PROFILE=one_way_diode` set on `watertwin-api`; startup
      fail-closed verified in the target environment (`/health` shows
      `platform_to_ot_enabled: false`).
- [ ] K8s `NetworkPolicy` denies `watertwin-api` any egress toward OT CIDRs.
- [ ] (Optional, strongest) a **hardware data diode** sits in the conduit so the
      one-way property is enforced physically, not only by policy.
