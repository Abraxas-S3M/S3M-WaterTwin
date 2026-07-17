#!/usr/bin/env bash
# Build Helm chart dependencies for the WaterTwin umbrella.
#
# Every component subchart depends on the local `watertwin-common` library
# chart via a file:// path. Helm needs that dependency vendored (as a .tgz under
# each subchart's charts/ dir) before `helm lint`, `helm template` or
# `helm install` will work. This script does that for every subchart and then
# the umbrella. Run it after checkout and whenever the library chart changes.
set -euo pipefail

HELM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UMBRELLA="${HELM_DIR}/watertwin"

echo "==> Building subchart dependencies (watertwin-common library)"
for chart in "${UMBRELLA}"/charts/*/; do
  if [[ -f "${chart}/Chart.yaml" ]]; then
    echo "    - $(basename "${chart}")"
    helm dependency build "${chart}" >/dev/null
  fi
done

echo "==> Building umbrella dependencies"
helm dependency build "${UMBRELLA}" >/dev/null

echo "OK: dependencies built."
