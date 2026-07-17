"""Lightweight, thread-safe counters for event-bus observability.

The bus records simple named counters (events published to the bus, publish
failures, degraded direct deliveries, handler errors, ...) so degradation is
*visible*: when the bus is unavailable the ``degraded_deliveries`` counter
climbs and the service keeps working via direct in-process delivery. The
counters are intentionally dependency-free (no Prometheus client required) and
can be surfaced in ``/health`` or scraped/exported by a caller.
"""

from __future__ import annotations

import threading
from collections import defaultdict

#: Canonical counter names the bus maintains.
PUBLISHED = "published"
PUBLISH_FAILURES = "publish_failures"
CONNECT_FAILURES = "connect_failures"
DEGRADED_DELIVERIES = "degraded_deliveries"
DIRECT_DELIVERIES = "direct_deliveries"
BUS_DELIVERIES = "bus_deliveries"
HANDLER_ERRORS = "handler_errors"


class BusMetrics:
    """A small thread-safe set of monotonically increasing counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)

    def inc(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def get(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    def snapshot(self) -> dict[str, int]:
        """Return a copy of all counters (safe to serialize)."""
        with self._lock:
            return dict(self._counters)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
