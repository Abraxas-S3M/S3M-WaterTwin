"""Container liveness check for the (portless) edge-gateway worker.

The gateway binds no inbound port, so the Docker HEALTHCHECK cannot curl an
endpoint. Instead it verifies the collection loop's heartbeat file is fresh
(touched within a bounded window). Exit code 0 = healthy, 1 = unhealthy.
"""

from __future__ import annotations

import os
import sys
import time

from . import config


def is_healthy(max_stale_s: float = 0.0) -> bool:
    path = config.HEARTBEAT_PATH
    if not path or not os.path.exists(path):
        return False
    if max_stale_s <= 0:
        # Default: three poll intervals of slack (min 30s).
        max_stale_s = max(30.0, config.POLL_INTERVAL_S * 3)
    age = time.time() - os.path.getmtime(path)
    return age <= max_stale_s


def main() -> int:
    return 0 if is_healthy() else 1


if __name__ == "__main__":
    sys.exit(main())
