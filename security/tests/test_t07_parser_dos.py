"""ADR-0014 T7 — Parser DoS (CPU/wall-clock timeout and memory cap).

Control: parse jobs run in a fresh child interpreter with OS-enforced limits
(RLIMIT_AS memory cap, RLIMIT_CPU + wall-clock timeout). A runaway parser is
killed; the ingest service itself is never affected.
"""

from __future__ import annotations

import time

import pytest
from app.limits import (
    ParseMemoryExceeded,
    ParseTimeout,
    run_sandboxed,
)


def test_timeout_is_enforced_and_parent_survives():
    start = time.monotonic()
    with pytest.raises(ParseTimeout):
        run_sandboxed("__sleep__", b"", timeout_s=1.0)
    elapsed = time.monotonic() - start
    # The job is killed near the deadline, not left running for its full sleep.
    assert elapsed < 20.0


def test_memory_cap_is_enforced():
    with pytest.raises(ParseMemoryExceeded):
        run_sandboxed(
            "__allocate__", b"", timeout_s=20.0, memory_bytes=256 * 1024 * 1024
        )


def test_a_normal_parse_still_completes_under_limits():
    result = run_sandboxed("csv", b"a,b\n1,2\n", timeout_s=10.0)
    assert result["rows"] == 2
