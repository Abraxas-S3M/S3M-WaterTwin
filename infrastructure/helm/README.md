# S3M-WaterTwin Helm charts

Kubernetes packaging for the advisory / read-only WaterTwin platform.

```
infrastructure/helm/
├── build-deps.sh          # vendors the library chart into every subchart
├── watertwin-common/      # library chart: shared Deployment/StatefulSet/
│                          # Service/ServiceAccount/Ingress + OT NetworkPolicy
└── watertwin/             # umbrella chart (deploy this)
    ├── Chart.yaml         # depends on the 7 component subcharts
    ├── values.yaml        # shared defaults (+ global.*)
    ├── values-dev.yaml    # environment overlays (applied with -f)
    ├── values-staging.yaml
    ├── values-prod.yaml
    └── charts/            # component subcharts
        ├── watertwin-api/
        ├── hydraulic-sim/
        ├── treatment-sim/
        ├── edge-gateway/
        ├── dashboard/
        ├── timescaledb/
        └── postgis/
```

## Quick start

```bash
# 1. Vendor chart dependencies (the watertwin-common library).
./infrastructure/helm/build-deps.sh

# 2. Lint + render.
helm lint infrastructure/helm/watertwin -f infrastructure/helm/watertwin/values-dev.yaml
helm template watertwin infrastructure/helm/watertwin \
  -n watertwin -f infrastructure/helm/watertwin/values-dev.yaml

# 3. Create the referenced Secrets (NO secrets live in these charts).
kubectl create namespace watertwin
kubectl -n watertwin create secret generic watertwin-db \
  --from-literal=postgres-password='<pw>' \
  --from-literal=database-url='postgresql://watertwin:<pw>@timescaledb:5432/watertwin'
kubectl -n watertwin create secret generic watertwin-postgis \
  --from-literal=postgres-password='<pw>'

# 4. Install.
helm upgrade --install watertwin infrastructure/helm/watertwin \
  -n watertwin -f infrastructure/helm/watertwin/values-dev.yaml
```

See [`docs/deployment/kubernetes.md`](../../docs/deployment/kubernetes.md) for
the full runbook, the NetworkPolicy / OT security model, and secret management.

## Security posture

- Namespace **default-deny** NetworkPolicy plus per-component allow-lists.
- OT reachability is **outbound-only**: the `edge-gateway` may only *initiate*
  connections to OT segments on read-only protocol ports; OT can never open a
  connection into the platform.
- **No secrets in values** — every credential is referenced from a pre-created
  Kubernetes Secret via `secretKeyRef`.
- Hardened pods: non-root, dropped capabilities, read-only rootfs (where the
  runtime allows), `seccompProfile: RuntimeDefault`, resource requests/limits,
  and liveness/readiness probes on every workload.
