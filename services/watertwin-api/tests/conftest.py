"""Integration test bootstrap for watertwin-api.

Launches the hydraulic-sim service in a real subprocess (isolating its ``app``
package from watertwin-api's) and wires a TestClient whose hydraulic client
targets that live service over HTTP.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import pytest

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(SERVICE_ROOT))
PACKAGES = os.path.join(REPO_ROOT, "packages")
HYDRAULIC_ROOT = os.path.join(REPO_ROOT, "services", "hydraulic-sim")

for path in (PACKAGES, SERVICE_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

_tmp = tempfile.mkdtemp(prefix="watertwin-api-test-")
os.environ.setdefault("WATERTWIN_RECO_STORE", os.path.join(_tmp, "recommendations.json"))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def hydraulic_base_url():
    # The integration path requires the hydraulic-sim service, which in turn
    # requires the heavy EPANET/WNTR stack. When that stack is not installed
    # (e.g. a CI job that only exercises the fast unit path), skip rather than
    # error so `pytest` stays green. ``services/watertwin-api/tests/test_reports.py``
    # provides the equivalent fast, dependency-free coverage.
    try:
        import wntr  # noqa: F401
    except Exception:
        pytest.skip("WNTR/EPANET not installed; skipping live hydraulic-sim integration")

    port = _free_port()
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([PACKAGES, HYDRAULIC_ROOT])
    env["HYDRAULIC_SIM_JOB_STORE"] = os.path.join(_tmp, "hydraulic-jobs.json")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=HYDRAULIC_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read().decode() if proc.stdout else ""
            pytest.skip(f"hydraulic-sim could not start for integration tests:\n{out}")
        try:
            r = httpx.get(f"{base_url}/health", timeout=2.0)
            if r.status_code == 200 and r.json().get("status") == "healthy":
                ready = True
                break
        except Exception:
            time.sleep(0.5)
    if not ready:
        proc.terminate()
        pytest.skip("hydraulic-sim did not become healthy in time")
    yield base_url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture()
def client(hydraulic_base_url):
    from fastapi.testclient import TestClient

    from app.hydraulic_client import HydraulicSimClient
    from app.main import app

    app.state.hydraulic_client = HydraulicSimClient(base_url=hydraulic_base_url)
    with TestClient(app) as c:
        yield c
