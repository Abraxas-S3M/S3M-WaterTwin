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

# Isolate the buffer + push config to throwaway defaults before app.config imports.
_tmp = tempfile.mkdtemp(prefix="edge-gateway-test-")
os.environ.setdefault("EDGE_GATEWAY_BUFFER_PATH", os.path.join(_tmp, "buffer.db"))
os.environ.setdefault("EDGE_GATEWAY_BUFFER_KEY", "test-buffer-key")
os.environ.setdefault("EDGE_GATEWAY_API_URL", "http://watertwin-api.test:8000")
