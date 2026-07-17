# Kubernetes deployment (Helm)

This document is the runbook for deploying S3M-WaterTwin to Kubernetes with the
Helm charts under [`infrastructure/helm`](../../infrastructure/helm). It covers
the chart layout, the zero-trust NetworkPolicy / OT security model, secret
management (no secrets are ever stored in the charts), and per-environment
install/upgrade/rollback.

Everything deployed here inherits the platform's **advisory / read-only** safety
posture (see [`docs/security/control-boundaries.md`](../security/control-boundaries.md)).
Nothing in these charts opens a control-write path, and the network policy makes
OT reachability strictly outbound-only.

## Contents

- [What gets deployed](#what-gets-deployed)
- [Prerequisites](#prerequisites)
- [Chart layout](#chart-layout)
- [Secrets (no secrets in values)](#secrets-no-secrets-in-values)
- [Install](#install)
- [Environments (dev / staging / prod)](#environments-dev--staging--prod)
- [NetworkPolicy & the OT read-only / outbound-only posture](#networkpolicy--the-ot-read-only--outbound-only-posture)
- [Resource limits, probes & hardening](#resource-limits-probes--hardening)
- [Upgrade & rollback](#upgrade--rollback)
- [Validation (helm lint + kubeconform)](#validation-helm-lint--kubeconform)
- [Troubleshooting](#troubleshooting)

## What gets deployed

| Component | Kind | Port | Notes |
|-----------|------|------|-------|
| `watertwin-api` | Deployment | 8000 | Simulation Center orchestration + audit trail. |
| `hydraulic-sim` | Deployment | 8100 | Read-only EPANET/WNTR what-if service. |
| `treatment-sim` | Deployment | 8080 | Read-only WaterTAP/IDAES RO service. |
| `edge-gateway`  | Deployment | 8200 | Read-only OT connectors; outbound-only to OT. |
| `dashboard`     | Deployment | 80   | Operator UI (nginx), proxies `/api` → API. |
| `timescaledb`   | StatefulSet | 5432 | TimescaleDB/PostgreSQL 16 (audit source of truth). |
| `postgis`       | StatefulSet | 5432 | PostGIS spatial/GIS store. |

Each component also gets a `Service`, a `ServiceAccount`, and a `NetworkPolicy`.
The umbrella additionally renders a namespace-wide default-deny `NetworkPolicy`.

## Prerequisites

- Kubernetes 1.26+ with a CNI that **enforces NetworkPolicy** (Calico, Cilium,
  Antrea, …). Without an enforcing CNI the policies are silently ignored.
- `helm` 3.14+ and `kubectl`.
- A default `StorageClass` (or set `*.persistence.storageClass` per environment)
  for the TimescaleDB / PostGIS PVCs.
- An ingress controller (e.g. ingress-nginx) if you enable ingress in
  staging/prod, and cert-manager if you use the sample TLS annotations.
- Container images pushed to a registry your cluster can pull
  (`global.imageRegistry`). The images are built from this repo's Dockerfiles.

## Chart layout

```
infrastructure/helm/
├── build-deps.sh          # vendors the library chart into every subchart
├── watertwin-common/      # library chart (shared templates)
└── watertwin/             # umbrella chart — deploy this one
    ├── values.yaml        # shared defaults + global.*
    ├── values-dev.yaml    # environment overlays (apply with -f)
    ├── values-staging.yaml
    ├── values-prod.yaml
    └── charts/            # the 7 component subcharts
```

`watertwin-common` is a Helm **library chart**: it holds the reusable
Deployment / StatefulSet / Service / ServiceAccount / Ingress / NetworkPolicy
templates so each component subchart stays a thin values file. Because it is a
`file://` dependency, it must be vendored once before rendering:

```bash
./infrastructure/helm/build-deps.sh   # or: make helm-deps
```

## Secrets (no secrets in values)

**No secret material lives in any chart or values file.** Every credential is
injected at runtime from a pre-created Kubernetes `Secret` via `secretKeyRef`
(rendered from each component's `secretEnv:` list). Create the secrets before
installing:

```bash
kubectl create namespace watertwin

# API + TimescaleDB. The API reads the full DSN; TimescaleDB reads the password.
kubectl -n watertwin create secret generic watertwin-db \
  --from-literal=postgres-password='<db-password>' \
  --from-literal=database-url='postgresql://watertwin:<db-password>@timescaledb:5432/watertwin'

# PostGIS.
kubectl -n watertwin create secret generic watertwin-postgis \
  --from-literal=postgres-password='<postgis-password>'

# OT connector credentials (only if edge-gateway uses an authenticated source,
# e.g. OPC UA). Referenced by edge-gateway.secretEnv in staging/prod values.
kubectl -n watertwin create secret generic edge-gateway-ot \
  --from-literal=opcua-username='<user>' \
  --from-literal=opcua-password='<password>'
```

For production, prefer sourcing these from an external secrets manager (e.g.
External Secrets Operator, Vault, or your cloud provider's CSI driver) that
creates the same secret names. The charts only reference the secret name + key,
so the source is entirely your choice.

The dashboard OIDC configuration is **not** a secret — it is baked into the
static bundle at image build time (`VITE_*` build args), and the API's OIDC
issuer/JWKS URLs are plain (non-secret) env values.

## Install

```bash
# 1. Vendor chart dependencies.
make helm-deps

# 2. Create the namespace + secrets (see previous section).

# 3. Install for the target environment.
helm upgrade --install watertwin infrastructure/helm/watertwin \
  -n watertwin --create-namespace \
  -f infrastructure/helm/watertwin/values-dev.yaml

# 4. Watch it come up.
kubectl -n watertwin get pods,svc,networkpolicy -l app.kubernetes.io/part-of=watertwin
```

Services resolve under stable in-cluster names (`watertwin-api`,
`hydraulic-sim`, `treatment-sim`, `dashboard`, `edge-gateway`, `timescaledb`,
`postgis`) regardless of the Helm release name, so the dashboard's nginx proxy
to `watertwin-api:8000` works out of the box.

## Environments (dev / staging / prod)

Environment differences are expressed entirely in the overlay values files,
layered on top of the subchart defaults with `-f`:

| Aspect | dev | staging | prod |
|--------|-----|---------|------|
| Replicas (api/dashboard) | 1 / 1 | 2 / 2 | 3 / 3 |
| Auth (OIDC) | bypassed (`WATERTWIN_AUTH_DISABLED=true`) | enforced | enforced |
| Ingress + TLS | off | on (staging host) | on (prod host, ssl-redirect) |
| Image tags | `latest` | pinned `0.1.0` | pinned `0.1.0` |
| Storage | small, default class | 10–20Gi, `standard` | 50–100Gi, `fast-ssd` |
| OT source | `synthetic` | real OPC UA + OT CIDR | real OPC UA + OT CIDR |
| OIDC egress | `0.0.0.0/0:443` | `0.0.0.0/0:443` | locked to IdP CIDR |
| NetworkPolicy default-deny | on | on | on |

Replace the example hostnames, registry, OT CIDRs and storage classes in
`values-staging.yaml` / `values-prod.yaml` with your real values.

```bash
# staging
helm upgrade --install watertwin infrastructure/helm/watertwin -n watertwin \
  -f infrastructure/helm/watertwin/values-staging.yaml

# prod
helm upgrade --install watertwin infrastructure/helm/watertwin -n watertwin \
  -f infrastructure/helm/watertwin/values-prod.yaml
```

## NetworkPolicy & the OT read-only / outbound-only posture

The charts implement a zero-trust network model built from two layers:

1. **Namespace default-deny** (`global.networkPolicy.defaultDeny`, on by
   default). A `NetworkPolicy` with an empty `podSelector` and both
   `Ingress` + `Egress` policy types denies all traffic for any pod that has no
   more-specific allow rule. Because NetworkPolicies are additive allow-lists,
   this is the safe baseline.

2. **Per-component allow-lists.** Every component chart renders its own
   `NetworkPolicy` granting only the connectivity it needs, expressed as
   structured `ingress` / `egress` peers (`component:` → pod selector,
   `namespace:` → namespace selector, `cidr:` → ipBlock). Cluster DNS is allowed
   via `allowDNS: true`.

The intended east-west graph:

```
             ingress-nginx ──▶ dashboard ──▶ watertwin-api ──▶ hydraulic-sim
                                    │              │       └──▶ treatment-sim
                                    └──────────────┘       ├──▶ timescaledb
                                                           └──▶ postgis (also ◀── hydraulic-sim)
   OT network  ◀── (outbound-only) ── edge-gateway ──▶ watertwin-api
```

### OT read-only + outbound-only egress (mirrors the read-only OT connector contract)

The `edge-gateway` runs the strictly read-only OT connectors (OPC UA / Modbus /
historian). Its `NetworkPolicy` mirrors the read-only OT connector security
contract (see [`docs/security/control-boundaries.md`](../security/control-boundaries.md)
and [`docs/architecture/s3m-core-contract.md`](../architecture/s3m-core-contract.md)):

- **No ingress from OT.** No component lists an OT CIDR as an ingress peer, and
  the default-deny drops everything else, so an OT segment can **never initiate**
  a connection into the platform.
- **Outbound-only egress to OT.** The gateway may only *initiate* connections
  toward the configured OT segment CIDR(s), and only on read-only protocol
  ports: OPC UA `4840/tcp`, Modbus `502/tcp`, historian `443/tcp`. Everything
  else is denied.
- The only other egress from the gateway is the telemetry push to
  `watertwin-api:8000` and cluster DNS.

Set the real OT CIDRs per environment under
`edge-gateway.networkPolicy.egress[].to[].cidr` (the defaults are RFC1918
placeholders that MUST be overridden for staging/prod). Because the gateway is
outbound-only and the connectors use read-only OPC UA/Modbus function codes and
read-only historian pulls, there is no path from the platform to actuate OT.

### Rendered policies

Rendering with any environment produces **8 NetworkPolicies** — one per
component plus the namespace default-deny. Inspect them with:

```bash
helm template watertwin infrastructure/helm/watertwin \
  -f infrastructure/helm/watertwin/values-prod.yaml \
  | yq 'select(.kind == "NetworkPolicy")'
```

## Resource limits, probes & hardening

Every workload sets:

- **Resource requests and limits** (CPU + memory), sized per environment.
- **Liveness and readiness probes** — HTTP `GET /health` for the API and
  simulation/edge services, HTTP `GET /` for the dashboard, and
  `pg_isready` exec probes for the databases.
- A hardened security context: `runAsNonRoot` + non-root UID for the app
  services, `allowPrivilegeEscalation: false`, `capabilities: drop [ALL]`,
  `readOnlyRootFilesystem` (where the runtime allows, with an `emptyDir` for
  scratch), and `seccompProfile: RuntimeDefault`.
- `automountServiceAccountToken: false` (no workload needs the API server).

## Upgrade & rollback

```bash
# Upgrade (re-uses the same values overlay).
helm upgrade watertwin infrastructure/helm/watertwin -n watertwin \
  -f infrastructure/helm/watertwin/values-prod.yaml

# Inspect history and roll back if needed.
helm history watertwin -n watertwin
helm rollback watertwin <REVISION> -n watertwin
```

StatefulSet PVCs are retained across upgrades and rollbacks, so the audit trail
and spatial data survive. For database backup/restore see
[`docs/deployment/backup-recovery.md`](./backup-recovery.md).

## Validation (helm lint + kubeconform)

CI runs `helm lint` and renders every environment through `kubeconform` against
the upstream Kubernetes schemas (see the `helm` job in
[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)). Reproduce locally:

```bash
make helm-deps

for env in dev staging prod; do
  helm lint infrastructure/helm/watertwin \
    -f infrastructure/helm/watertwin/values-$env.yaml
  helm template watertwin infrastructure/helm/watertwin -n watertwin \
    -f infrastructure/helm/watertwin/values-$env.yaml \
    | kubeconform -strict -summary -kubernetes-version 1.29.0 -schema-location default
done
```

## Troubleshooting

- **Pods stuck `CrashLoopBackOff` on the DB / API**: the referenced Secret is
  missing or has the wrong key. Confirm `watertwin-db` / `watertwin-postgis`
  exist in the namespace with the expected keys.
- **API cannot reach a sim service or the DB**: verify your CNI enforces
  NetworkPolicy and that the peer `component:`/`namespace:` selectors match your
  cluster (e.g. your ingress controller namespace may not be `ingress-nginx`).
- **edge-gateway cannot read OT**: confirm the OT CIDR + ports in
  `edge-gateway.networkPolicy.egress` match the real OT segment, and that the
  OT endpoint env (`OT_OPCUA_ENDPOINT`, etc.) and `edge-gateway-ot` secret are
  set. Remember the gateway is outbound-only by design.
- **`helm template` errors about a missing `watertwin-common` template**: run
  `make helm-deps` to vendor the library dependency first.
- **PVC pending**: no default StorageClass — set `*.persistence.storageClass`.
```
