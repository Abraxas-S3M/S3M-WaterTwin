"""Guardrail: every (path, method) is registered exactly once, in every service.

FastAPI resolves the *first* matching registration for a path, so a duplicate
route silently shadows the later handler. That is exactly what made the model
governance registry (``GET /api/v1/models``) unreachable: a second handler on
the same path was never reached and its ``count`` payload never shipped.

This asserts there are no duplicate ``(path, method)`` pairs. It runs against
**every** FastAPI service in the repo, not just watertwin-api, so the shadowing
class of bug cannot recur anywhere.

Each service is imported in an isolated subprocess (they all ship a top-level
``app`` package, which cannot coexist in one interpreter). A service whose app
cannot be imported here — a missing optional dependency in this environment, or
a syntax error — is skipped rather than failed: importability is a separate,
louder invariant already gated by the CI ``import-guard`` job. Keeping the two
guards separate means each fails for exactly one reason.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections import Counter

import pytest

from app.main import app

# services/watertwin-api/tests/ -> services/watertwin-api/ -> services/ -> repo
_SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(_SERVICE_ROOT))
PACKAGES = os.path.join(REPO_ROOT, "packages")

# The HTTP services (edge-gateway is deliberately excluded: it is an
# outbound-only collection worker that binds no listener and has no app).
FASTAPI_SERVICES = (
    "watertwin-api",
    "hydraulic-sim",
    "treatment-sim",
    "watertwin-ingest",
)

# Small program run inside each service's directory to dump its registered
# (path, method) pairs as JSON. Kept dependency-free on purpose. The payload is
# emitted on a sentinel-prefixed line so structured logs a service writes to
# stdout at import time cannot corrupt the JSON we parse back.
_ROUTES_SENTINEL = "__WATERTWIN_ROUTES__:"
_DUMP_ROUTES = f"""
import json
from app.main import app

pairs = []
for route in getattr(app, "routes", []):
    path = getattr(route, "path", None)
    methods = getattr(route, "methods", None)
    if path is None or not methods:
        continue
    for method in methods:
        pairs.append((path, method))
print("{_ROUTES_SENTINEL}" + json.dumps(pairs))
"""


def _route_method_pairs_in_process() -> list[tuple[str, str]]:
    """Every registered ``(path, method)`` pair for the in-process app."""
    pairs: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is None or not methods:
            continue
        for method in methods:
            pairs.append((path, method))
    return pairs


def _route_method_pairs_for_service(service: str) -> list[tuple[str, str]]:
    """Import ``service`` in an isolated subprocess and return its route pairs.

    Skips the test (rather than failing) when the service app cannot be imported
    in this environment — that importability invariant is the ``import-guard``
    job's responsibility.
    """
    service_dir = os.path.join(REPO_ROOT, "services", service)
    scratch = tempfile.mkdtemp(prefix=f"routes-{service}-")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([PACKAGES, service_dir])
    # Import-time side effects (store/spool creation) must land somewhere
    # writable and disposable; auth is disabled so no identity provider is hit.
    env.setdefault("WATERTWIN_AUTH_DISABLED", "true")
    env["EDGE_SPOOL_DIR"] = os.path.join(scratch, "edge-spool")
    env["INGEST_STORAGE_ROOT"] = os.path.join(scratch, "ingest-store")
    env["HYDRAULIC_SIM_JOB_STORE"] = os.path.join(scratch, "hydraulic-jobs.json")
    env["WATERTWIN_RECO_STORE"] = os.path.join(scratch, "recommendations.json")

    proc = subprocess.run(
        [sys.executable, "-c", _DUMP_ROUTES],
        cwd=service_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(
            f"{service} app is not importable in this environment "
            f"(gated separately by import-guard):\n{proc.stderr.strip()[-1500:]}"
        )
    payload = next(
        (
            line[len(_ROUTES_SENTINEL):]
            for line in proc.stdout.splitlines()
            if line.startswith(_ROUTES_SENTINEL)
        ),
        None,
    )
    assert payload is not None, f"{service}: route dump produced no payload:\n{proc.stdout[-1500:]}"
    return [tuple(pair) for pair in json.loads(payload)]


@pytest.mark.parametrize("service", FASTAPI_SERVICES)
def test_no_duplicate_route_registrations(service: str) -> None:
    pairs = _route_method_pairs_for_service(service)
    duplicates = {pair: count for pair, count in Counter(pairs).items() if count > 1}
    assert not duplicates, f"{service}: duplicate (path, method) registrations: {duplicates}"


def test_models_registry_is_the_only_models_handler() -> None:
    # Regression lock for the specific bug: exactly one GET /api/v1/models in
    # watertwin-api (checked in-process against the app under test).
    models_get = [
        pair
        for pair in _route_method_pairs_in_process()
        if pair == ("/api/v1/models", "GET")
    ]
    assert len(models_get) == 1
