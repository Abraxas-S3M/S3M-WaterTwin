"""Data-quality flagging: range / staleness / frozen-signal / deadband."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone


from app import quality
from app.quality import QualityMonitor


def _now():
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_good_reading_is_flagged_good():
    mon = QualityMonitor(staleness_limit_s=60, frozen_limit=3, deadband=0.0)
    result = mon.evaluate("AST-HPP-01", "winding_temp_c", 150.0, _now().isoformat(), now=_now())
    assert result.flag == quality.GOOD
    assert result.valid is True


def test_out_of_range_is_flagged_and_invalid():
    mon = QualityMonitor(staleness_limit_s=60, frozen_limit=3)
    # winding_temp_c default range is (0, 200); 500 is out of range.
    result = mon.evaluate("AST-HPP-01", "winding_temp_c", 500.0, _now().isoformat(), now=_now())
    assert result.flag == quality.OUT_OF_RANGE
    assert result.valid is False
    assert quality.OUT_OF_RANGE in result.reasons


def test_stale_reading_is_flagged():
    mon = QualityMonitor(staleness_limit_s=60, frozen_limit=3)
    old_ts = (_now() - timedelta(seconds=120)).isoformat()
    result = mon.evaluate("AST-HPP-01", "winding_temp_c", 150.0, old_ts, now=_now())
    assert result.flag == quality.STALE
    assert result.valid is True


def test_frozen_signal_is_flagged_after_repeat_limit():
    mon = QualityMonitor(staleness_limit_s=1e9, frozen_limit=3, deadband=0.0)
    ts = _now().isoformat()
    flags = [
        mon.evaluate("AST-HPP-01", "vibration_mm_s", 6.4, ts, now=_now()).flag
        for _ in range(3)
    ]
    # First two identical samples are still "good"; the third crosses the limit.
    assert flags[0] == quality.GOOD
    assert flags[1] == quality.GOOD
    assert flags[2] == quality.FROZEN


def test_frozen_resets_when_value_changes():
    mon = QualityMonitor(staleness_limit_s=1e9, frozen_limit=3)
    ts = _now().isoformat()
    mon.evaluate("AST-HPP-01", "vibration_mm_s", 6.4, ts, now=_now())
    mon.evaluate("AST-HPP-01", "vibration_mm_s", 6.4, ts, now=_now())
    changed = mon.evaluate("AST-HPP-01", "vibration_mm_s", 7.0, ts, now=_now())
    assert changed.flag == quality.GOOD


def test_deadband_change_is_flagged():
    mon = QualityMonitor(staleness_limit_s=1e9, frozen_limit=1000, deadband=0.5)
    ts = _now().isoformat()
    mon.evaluate("AST-HPP-01", "vibration_mm_s", 6.40, ts, now=_now())
    # A change smaller than the 0.5 deadband is an insignificant change.
    result = mon.evaluate("AST-HPP-01", "vibration_mm_s", 6.45, ts, now=_now())
    assert result.flag == quality.DEADBAND


def test_non_finite_value_is_flagged_invalid():
    mon = QualityMonitor()
    result = mon.evaluate("AST-HPP-01", "winding_temp_c", math.inf, _now().isoformat(), now=_now())
    assert result.flag == quality.NON_FINITE
    assert result.valid is False


def test_out_of_range_takes_priority_over_stale():
    mon = QualityMonitor(staleness_limit_s=60, frozen_limit=3)
    old_ts = (_now() - timedelta(seconds=120)).isoformat()
    result = mon.evaluate("AST-HPP-01", "winding_temp_c", 999.0, old_ts, now=_now())
    assert result.flag == quality.OUT_OF_RANGE
    # Both reasons are recorded even though range is the primary flag.
    assert quality.OUT_OF_RANGE in result.reasons
    assert quality.STALE in result.reasons
