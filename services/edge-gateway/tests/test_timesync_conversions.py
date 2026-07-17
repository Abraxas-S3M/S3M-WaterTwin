"""Time-sync/monotonic timestamping + unit conversion + source-health tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.conversions import to_canonical
from app.health import DEGRADED, DOWN, HEALTHY, SourceHealth
from app.timesync import MonotonicClock


def test_monotonic_timestamps_never_go_backwards():
    # A clock that steps backwards on the second call.
    seq = iter(
        [
            datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),  # backwards step
            datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),  # duplicate
        ]
    )
    clock = MonotonicClock(now_fn=lambda: next(seq))
    t1, _ = clock.stamp()
    t2, _ = clock.stamp()
    t3, _ = clock.stamp()
    assert t1 < t2 < t3  # strictly increasing despite the backward wall clock


def test_clock_reports_source_skew():
    fixed = datetime(2026, 1, 1, 0, 0, 30, tzinfo=timezone.utc)
    clock = MonotonicClock(now_fn=lambda: fixed)
    source_ts = (fixed - timedelta(seconds=5)).isoformat()
    _, skew = clock.stamp(source_ts)
    assert skew == pytest.approx(5.0)


def test_unit_conversion_to_canonical():
    # Fahrenheit -> Celsius.
    value, unit = to_canonical(302.0, "degF")
    assert unit == "degC"
    assert value == pytest.approx(150.0, abs=1e-6)
    # kPa -> bar.
    value, unit = to_canonical(100.0, "kPa")
    assert unit == "bar"
    assert value == pytest.approx(1.0)
    # Already-canonical / unknown units pass through unchanged.
    assert to_canonical(6.4, "mm/s") == (6.4, "mm/s")
    assert to_canonical(1.0, "widgets") == (1.0, "widgets")


def test_source_health_status_transitions():
    health = SourceHealth(gateway_id="gw")
    assert health.status == HEALTHY

    # A synthetic fallback is a degraded (but running) state.
    health.fallback = True
    assert health.status == DEGRADED
    health.fallback = False

    # A failing real read with no fallback is down.
    health.record_read_failure("boom")
    assert health.status == DOWN
    health.record_read_success(3)
    assert health.status == HEALTHY

    # Buffering because forwarding fails is degraded.
    health.record_forward_failure("net")
    assert health.status == DEGRADED
    snap = health.snapshot()
    assert snap["gateway_id"] == "gw"
    assert snap["total_readings"] == 3
    assert snap["consecutive_forward_failures"] == 1
