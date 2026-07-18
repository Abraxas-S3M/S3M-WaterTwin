"""Test bootstrap: make shared packages + the service app importable, isolate state."""

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

# Isolate the sandbox scratch directory before the app imports config.
_tmp = tempfile.mkdtemp(prefix="watertwin-ingest-test-")
os.environ.setdefault("WATERTWIN_INGEST_SCRATCH_DIR", os.path.join(_tmp, "scratch"))

#: Path to the bundled RO/pumping-station demo network (shared with the twin).
DEMO_INP = os.path.join(PACKAGES, "network_twin", "networks", "ro-handoff.inp")
