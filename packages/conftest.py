"""Test bootstrap: put the shared ``packages/`` directory on ``sys.path``.

Lets the package test-suite import ``watertwin_engineering``,
``canonical_water_model`` and ``simulation_contracts`` without an install step.
"""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGES_ROOT = Path(__file__).resolve().parent

if str(PACKAGES_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGES_ROOT))
