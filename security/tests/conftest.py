"""Bootstrap for the ADR-0014 ingestion threat-model test suite.

Makes the shared packages and the ``watertwin-ingest`` service importable so each
threat-model row can be proven against the *real* service code (not a stand-in).
"""

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGES = os.path.join(REPO_ROOT, "packages")
INGEST_ROOT = os.path.join(REPO_ROOT, "services", "watertwin-ingest")

for path in (PACKAGES, INGEST_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
