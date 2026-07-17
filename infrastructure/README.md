# Infrastructure manifests

Deployment-side manifests for S3M-WaterTwin. See
[`docs/deployment/edge-xiid-reference.md`](../docs/deployment/edge-xiid-reference.md)
for the full edge / XiiD-ready reference topology and how these files enforce a
one-way / data-diode posture at the network layer.

| Path | Purpose |
|------|---------|
| `database/init.sql` | TimescaleDB / Postgres schema bootstrap (audit + recommendations). |
| `keycloak/watertwin-realm.json` | Keycloak realm for identity / RBAC. |
| `network-policy/00-default-deny.yaml` | Namespace baseline: deny all ingress/egress by default. |
| `network-policy/watertwin-api-networkpolicy.yaml` | Selector-based ingress/egress allowlist for `watertwin-api` (no egress toward OT). |
| `network-policy/watertwin-api-egress-allowlist.yaml` | CIDR-based egress allowlist; OT zone CIDRs are excluded (`ipBlock.except`). |
| `gateway/watertwin-api-mtls.conf` | Platform-side nginx terminating the edge gateway's outbound mTLS tunnel (ingestion/push-only). |
| `gateway/edge-gateway-outbound.conf` | OT-side edge gateway nginx: outbound-only + mTLS client (gateway-push-only). |

## One-way / data-diode profile (`DEPLOYMENT_PROFILE=one_way_diode`)

These manifests are the **network-layer** half of the guarantee; the
**application-layer** half is the fail-closed check in
[`services/watertwin-api/app/deployment.py`](../services/watertwin-api/app/deployment.py).
Together they ensure the platform never initiates a connection toward the OT
zone:

1. `00-default-deny.yaml` — every pod starts with zero reachability.
2. `watertwin-api-networkpolicy.yaml` / `watertwin-api-egress-allowlist.yaml` —
   re-open only the enterprise/cloud flows; **no** rule permits egress toward OT
   CIDRs or OT protocols (OPC UA 4840 / Modbus 502 / historian REST/SQL).
3. `gateway/*.conf` — the edge gateway pushes **outbound** over mTLS; the
   platform-side proxy only **terminates** that tunnel and exposes an
   ingestion-only surface. Neither side opens a path from platform into OT.

> Xiid ZKN crypto / SealedTunnel transport is **not** reimplemented in this repo.
> The nginx configs express the outbound-only + mTLS posture that layers on top
> of the Xiid connector (XOTC / mesh connector). Adjust namespaces, labels,
> CIDRs, and certificate paths to match your environment before applying.
