"""Test bootstrap: make shared packages + service importable and isolate state."""

from __future__ import annotations

import os
import sys
import tempfile

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(SERVICE_ROOT))
PACKAGES = os.path.join(REPO_ROOT, "packages")

for path in (PACKAGES, SERVICE_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

# Isolate the job store to a throwaway file before the app imports config.
_tmp = tempfile.mkdtemp(prefix="hydraulic-sim-test-")
os.environ.setdefault("HYDRAULIC_SIM_JOB_STORE", os.path.join(_tmp, "jobs.json"))
