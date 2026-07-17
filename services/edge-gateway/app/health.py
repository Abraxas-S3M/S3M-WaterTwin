"""Source-health reporting.

Tracks the health of the active OT source and the outbound push path: read
success/failure, active-vs-requested source and any synthetic fallback, forward
success/failure (store-and-forward backlog), clock skew, and counters. Because
the gateway is OUTBOUND-ONLY it does not expose a health endpoint; instead the
current snapshot is attached to every pushed batch and logged, so the API-side
``/api/v1/ingestion/telemetry/latest`` view surfaces per-gateway health.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from canonical_water_model import now_iso

HEALTHY = "healthy"
DEGRADED = "degraded"
DOWN = "down"


@dataclass
class SourceHealth:
    """Mutable health state for the gateway's active source + push path."""

    gateway_id: str
    requested_source: str = "synthetic"
    active_source: str = "synthetic"
    fallback: bool = False
    fallback_reason: Optional[str] = None

    consecutive_read_failures: int = 0
    consecutive_forward_failures: int = 0
    total_reads: int = 0
    total_readings: int = 0
    total_forwarded: int = 0
    last_read_at: Optional[str] = None
    last_forward_at: Optional[str] = None
    last_error: Optional[str] = None
    last_error_at: Optional[str] = None
    last_skew_s: float = 0.0
    buffer_depth: int = 0

    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # -- resolution -----------------------------------------------------------

    def update_resolution(self, resolution: Any) -> None:
        with self._lock:
            self.requested_source = getattr(resolution, "requested", self.requested_source)
            self.active_source = getattr(resolution, "active", self.active_source)
            self.fallback = bool(getattr(resolution, "fallback", False))
            self.fallback_reason = getattr(resolution, "reason", None)

    # -- read path ------------------------------------------------------------

    def record_read_success(self, n_readings: int) -> None:
        with self._lock:
            self.consecutive_read_failures = 0
            self.total_reads += 1
            self.total_readings += n_readings
            self.last_read_at = now_iso()

    def record_read_failure(self, error: str) -> None:
        with self._lock:
            self.consecutive_read_failures += 1
            self.last_error = error
            self.last_error_at = now_iso()

    # -- forward path ---------------------------------------------------------

    def record_forward_success(self, n_forwarded: int) -> None:
        with self._lock:
            self.consecutive_forward_failures = 0
            self.total_forwarded += n_forwarded
            self.last_forward_at = now_iso()

    def record_forward_failure(self, error: str) -> None:
        with self._lock:
            self.consecutive_forward_failures += 1
            self.last_error = error
            self.last_error_at = now_iso()

    def set_skew(self, skew_s: float) -> None:
        with self._lock:
            self.last_skew_s = skew_s

    def set_buffer_depth(self, depth: int) -> None:
        with self._lock:
            self.buffer_depth = depth

    # -- derived status -------------------------------------------------------

    @property
    def status(self) -> str:
        with self._lock:
            if self.consecutive_read_failures > 0 and not self.fallback:
                return DOWN
            if self.fallback or self.consecutive_forward_failures > 0:
                return DEGRADED
            return HEALTHY

    def snapshot(self) -> dict[str, Any]:
        """A JSON-safe health snapshot for the push payload + logs."""
        with self._lock:
            return {
                "status": self.status,
                "gateway_id": self.gateway_id,
                "requested_source": self.requested_source,
                "active_source": self.active_source,
                "fallback": self.fallback,
                "fallback_reason": self.fallback_reason,
                "consecutive_read_failures": self.consecutive_read_failures,
                "consecutive_forward_failures": self.consecutive_forward_failures,
                "total_reads": self.total_reads,
                "total_readings": self.total_readings,
                "total_forwarded": self.total_forwarded,
                "buffer_depth": self.buffer_depth,
                "last_read_at": self.last_read_at,
                "last_forward_at": self.last_forward_at,
                "last_error": self.last_error,
                "last_error_at": self.last_error_at,
                "clock_skew_s": self.last_skew_s,
            }
