"""Test path setup.

Puts the repo root, the shared ``packages/`` directory, and the service root on
``sys.path`` so tests can import ``app.*``, ``simulation_contracts``,
``canonical_water_model`` and ``watertwin.*`` without an install step.
"""

from __future__ import annotations

import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]

for path in (REPO_ROOT, REPO_ROOT / "packages", SERVICE_ROOT):
    p = str(path)
    if p not in sys.path:
        sys.path.insert(0, p)
