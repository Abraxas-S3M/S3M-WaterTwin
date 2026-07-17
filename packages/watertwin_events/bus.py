"""The advisory event bus with graceful degradation.

:class:`EventBus` is the single publish/subscribe entry point every service
uses. It wraps a pluggable :class:`~watertwin_events.transport.Transport` (NATS
in production; in-process for tests/defaults) and guarantees three things:

1. **Advisory-only.** Every publish/subscribe subject is validated by
   :func:`~watertwin_events.subjects.assert_advisory_subject`, so a control
   command can never be placed on the bus.
2. **Graceful degradation.** If the bus (transport) is unavailable -- not
   configured, failed to connect, or a publish errors -- the bus does *not*
   raise. It logs a warning, increments a metric, and **falls back to direct
   in-process delivery** to any locally registered handlers so the calling
   service keeps working.
3. **Observability.** All outcomes are counted in a
   :class:`~watertwin_events.metrics.BusMetrics` snapshot.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable

from . import metrics as m
from .envelope import EventEnvelope, build_envelope
from .metrics import BusMetrics
from .subjects import assert_advisory_subject
from .transport import Transport

#: A bus subscriber receives a parsed :class:`EventEnvelope`.
EventHandler = Callable[[EventEnvelope], None]


class EventBus:
    """Publish/subscribe advisory service events with graceful degradation."""

    def __init__(
        self,
        *,
        source: str = "watertwin",
        transport: Transport | None = None,
        metrics: BusMetrics | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._source = source
        self._transport = transport
        self._metrics = metrics or BusMetrics()
        self._logger = logger or logging.getLogger("watertwin.events")
        # subject -> local handlers, used both for real subscriptions and as the
        # direct-call fallback target when the bus is degraded.
        self._handlers: dict[str, list[EventHandler]] = {}
        # Subjects with a live transport subscription (one per subject; the
        # single transport callback fans out to every local handler).
        self._transport_bound: set[str] = set()
        self._connect_attempted = False

    # -- lifecycle ------------------------------------------------------------

    @property
    def metrics(self) -> BusMetrics:
        return self._metrics

    @property
    def source(self) -> str:
        return self._source

    @property
    def has_transport(self) -> bool:
        return self._transport is not None

    @property
    def connected(self) -> bool:
        """True only when a transport is configured *and* currently connected."""
        return bool(self._transport is not None and self._transport.connected)

    @property
    def degraded(self) -> bool:
        """True when there is no live transport (publishes go direct)."""
        return not self.connected

    def connect(self) -> bool:
        """Attempt to bring the transport online (idempotent, never raises).

        Returns ``True`` on success. On any failure the bus logs, counts a
        ``connect_failures`` metric, and stays in the degraded (direct-delivery)
        mode -- it never propagates the error to the caller.
        """
        self._connect_attempted = True
        if self._transport is None:
            self._logger.info(
                "event bus has no transport configured; running in degraded "
                "(direct in-process delivery) mode"
            )
            return False
        try:
            self._transport.connect()
        except Exception as exc:
            self._metrics.inc(m.CONNECT_FAILURES)
            self._logger.warning(
                "event bus transport unavailable (%s); degrading to direct "
                "in-process delivery",
                exc,
            )
            return False
        # Re-attach any subjects registered before the transport came online.
        for subject in list(self._handlers):
            self._bind_transport_subscription(subject)
        self._logger.info("event bus connected via transport")
        return True

    def close(self) -> None:
        self._transport_bound.clear()
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception as exc:  # pragma: no cover - best effort
                self._logger.warning("event bus transport close failed: %s", exc)

    # -- subscribe ------------------------------------------------------------

    def subscribe(self, subject: str, handler: EventHandler) -> None:
        """Register a handler for an advisory ``subject``.

        The handler is always recorded locally (so it can receive events via the
        direct-call fallback when the bus is degraded) and, when a transport is
        connected, also bound to the transport subscription.
        """
        assert_advisory_subject(subject)
        self._handlers.setdefault(subject, []).append(handler)
        if self.connected:
            self._bind_transport_subscription(subject)

    def _bind_transport_subscription(self, subject: str) -> None:
        # Bind a single transport subscription per subject; its callback fans
        # out to every local handler, so multiple subscribers never double-deliver.
        if self._transport is None or subject in self._transport_bound:
            return
        try:
            self._transport.subscribe(subject, functools.partial(self._on_wire, subject))
            self._transport_bound.add(subject)
        except Exception as exc:  # pragma: no cover - transport dependent
            self._logger.warning("failed to subscribe to %s on transport: %s", subject, exc)

    def _on_wire(self, subject: str, data: bytes) -> None:
        """Transport callback: parse the envelope and dispatch to handlers."""
        try:
            envelope = EventEnvelope.from_bytes(data)
        except Exception as exc:  # pragma: no cover - defensive
            self._metrics.inc(m.HANDLER_ERRORS)
            self._logger.warning("dropping malformed event on %s: %s", subject, exc)
            return
        self._dispatch(subject, envelope, counter=m.BUS_DELIVERIES)

    def _dispatch(self, subject: str, envelope: EventEnvelope, *, counter: str) -> None:
        for handler in list(self._handlers.get(subject, ())):
            try:
                handler(envelope)
                self._metrics.inc(counter)
            except Exception as exc:
                self._metrics.inc(m.HANDLER_ERRORS)
                self._logger.warning("event handler error for %s: %s", subject, exc)

    # -- publish --------------------------------------------------------------

    def publish(
        self,
        subject: str,
        payload: dict | None = None,
        *,
        facility_id: str | None = None,
        train_id: str | None = None,
    ) -> EventEnvelope:
        """Publish an advisory event, degrading to direct delivery on failure.

        Builds a guarded :class:`EventEnvelope`, attempts to publish it via the
        transport, and -- if the transport is absent, disconnected, or errors --
        falls back to direct in-process delivery (log + metric). Never raises for
        a bus outage; it only raises
        :class:`~watertwin_events.subjects.ControlCommandOnBusError` if the
        subject is not advisory (a programming error, caught by the guard test).
        """
        envelope = build_envelope(
            subject,
            payload,
            source=self._source,
            facility_id=facility_id,
            train_id=train_id,
        )

        if self.connected:
            try:
                self._transport.publish(subject, envelope.to_bytes())
                self._metrics.inc(m.PUBLISHED)
                return envelope
            except Exception as exc:
                self._metrics.inc(m.PUBLISH_FAILURES)
                self._logger.warning(
                    "event publish failed for %s (%s); falling back to direct "
                    "in-process delivery",
                    subject,
                    exc,
                )
        # Degraded path: the bus is unavailable -> deliver directly.
        self._metrics.inc(m.DEGRADED_DELIVERIES)
        self._dispatch(subject, envelope, counter=m.DIRECT_DELIVERIES)
        return envelope

    # -- introspection --------------------------------------------------------

    def status(self) -> dict:
        """Return a JSON-serializable snapshot of bus state + metrics."""
        return {
            "source": self._source,
            "transport_configured": self.has_transport,
            "connected": self.connected,
            "degraded": self.degraded,
            "connect_attempted": self._connect_attempted,
            "subjects": sorted(self._handlers),
            "metrics": self._metrics.snapshot(),
        }
