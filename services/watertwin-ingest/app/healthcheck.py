"""Container HEALTHCHECK entrypoint (no shell required in the runtime image).

Run as ``python -m app.healthcheck``. Exits 0 when the ingest service is healthy
and the advisory/read-only safety invariant is intact, non-zero otherwise. It
performs an in-process check only — it does not open any socket — so it works in
a locked-down, read-only, no-shell container.
"""

from __future__ import annotations

import sys

from .control_boundary import safety_invariant_intact


def main() -> int:
    if not safety_invariant_intact():
        print("UNHEALTHY: safety invariant not intact", file=sys.stderr)
        return 1
    print("OK: watertwin-ingest healthy; advisory/read-only invariant intact")
    return 0


if __name__ == "__main__":  # pragma: no cover - invoked by the container runtime
    raise SystemExit(main())
