"""D1 false-alarm tracking (online false-positive accounting).

A :class:`FalseAlarmTracker` records raised alerts together with the operator's
eventual disposition (was the alert a true event or a false alarm?) over a
sliding window, and reports the running false-alarm rate. This closes the
feedback loop the platform previously lacked: alerts route through the existing
operator-approval path, and their dispositions feed this tracker so a model's
preliminary thresholds can be tuned against the site's real false-positive
tolerance.

Pure and deterministic; holds only an in-memory bounded window and never writes
to any control system.
"""

from __future__ import annotations

from collections import deque

from pydantic import BaseModel

from canonical_water_model import DataProvenance


class FalseAlarmSummary(BaseModel):
    """Windowed false-alarm accounting for one model (preliminary)."""

    model_config = {"protected_namespaces": ()}

    model_id: str
    window: int
    alerts_in_window: int
    true_alerts: int
    false_alarms: int
    pending: int
    false_alarm_rate: float
    target_false_alarm_rate: float
    within_target: bool
    provenance: DataProvenance = DataProvenance.preliminary


class FalseAlarmTracker:
    """Sliding-window false-alarm accounting against operator dispositions.

    Each raised alert is recorded via :meth:`record`; its disposition is either
    supplied immediately (``true_event=True/False``) or left ``None`` (pending
    operator review) and resolved later via :meth:`resolve`. :meth:`summary`
    reports the false-alarm rate over the most recent ``window`` alerts.
    """

    def __init__(
        self,
        model_id: str,
        window: int = 100,
        target_false_alarm_rate: float = 0.05,
    ) -> None:
        if window <= 0:
            raise ValueError("window must be positive.")
        if not 0.0 <= target_false_alarm_rate <= 1.0:
            raise ValueError("target_false_alarm_rate must be in [0, 1].")
        self.model_id = model_id
        self.window = window
        self.target_false_alarm_rate = target_false_alarm_rate
        # Each entry: [alert_id, true_event|None].
        self._events: deque[list] = deque(maxlen=window)
        self._index: dict[str, list] = {}

    def record(self, alert_id: str, true_event: bool | None = None) -> None:
        """Record a raised alert (optionally with its known disposition)."""
        entry = [alert_id, true_event]
        # deque drops the oldest when full; keep the id index consistent.
        if len(self._events) == self.window and self._events:
            dropped = self._events[0]
            self._index.pop(dropped[0], None)
        self._events.append(entry)
        self._index[alert_id] = entry

    def resolve(self, alert_id: str, true_event: bool) -> None:
        """Resolve a previously recorded alert as a true event or false alarm."""
        entry = self._index.get(alert_id)
        if entry is not None:
            entry[1] = true_event

    def summary(self) -> FalseAlarmSummary:
        """Return the windowed false-alarm summary for this model."""
        alerts = len(self._events)
        true_alerts = sum(1 for _, disp in self._events if disp is True)
        false_alarms = sum(1 for _, disp in self._events if disp is False)
        pending = sum(1 for _, disp in self._events if disp is None)
        resolved = true_alerts + false_alarms
        rate = round(false_alarms / resolved, 4) if resolved else 0.0
        return FalseAlarmSummary(
            model_id=self.model_id,
            window=self.window,
            alerts_in_window=alerts,
            true_alerts=true_alerts,
            false_alarms=false_alarms,
            pending=pending,
            false_alarm_rate=rate,
            target_false_alarm_rate=self.target_false_alarm_rate,
            within_target=rate <= self.target_false_alarm_rate,
        )
