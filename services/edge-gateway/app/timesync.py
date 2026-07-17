"""Time synchronization + monotonic timestamping.

OT feeds and edge clocks drift; buffered readings must also stay correctly
ordered even if the wall clock steps backwards (NTP correction, VM pause). This
module stamps every reading with a **monotonically non-decreasing** gateway
receipt timestamp and reports the observed skew between the gateway clock and the
source timestamp so the source-health view can surface a drifting clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

_EPSILON = timedelta(microseconds=1)


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        value = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class MonotonicClock:
    """Emits non-decreasing UTC timestamps and tracks source-clock skew."""

    def __init__(self, now_fn: Optional[Callable[[], datetime]] = None) -> None:
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._last: Optional[datetime] = None
        #: Most recent observed skew (gateway_receipt - source_timestamp), seconds.
        self.last_skew_s: float = 0.0

    def _now(self) -> datetime:
        now = self._now_fn()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now

    def stamp(self, source_ts: Optional[str] = None) -> tuple[str, float]:
        """Return ``(monotonic_gateway_iso, skew_seconds)`` for a reading.

        The returned timestamp is guaranteed to be strictly greater than the
        previously emitted one, so buffered/forwarded readings retain their
        collection order even across a backwards wall-clock step.
        """
        base = self._now()
        if self._last is not None and base <= self._last:
            base = self._last + _EPSILON
        self._last = base

        source = _parse_ts(source_ts)
        skew = (base - source).total_seconds() if source is not None else 0.0
        self.last_skew_s = skew
        return base.isoformat(), skew
