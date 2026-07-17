"""Pluggable transports for the event bus.

The bus is transport-agnostic. Two transports ship here:

* :class:`NatsTransport` -- the real NATS transport (via ``nats-py``). It runs
  the async NATS client on a dedicated background asyncio loop so the
  synchronous FastAPI request handlers can publish/subscribe without becoming
  async. If ``nats-py`` is missing or the broker is unreachable the transport
  raises on ``connect``/``publish`` and the bus degrades gracefully.
* :class:`InProcessTransport` -- an in-memory pub/sub used by tests and as a
  zero-dependency default. It delivers a published message synchronously to
  every subscriber, which makes the publish/subscribe round-trip fully testable
  without a broker.

A transport delivers raw ``bytes`` to subscriber callbacks; the bus is
responsible for (de)serializing the :class:`~watertwin_events.envelope.EventEnvelope`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Protocol, runtime_checkable

#: A transport subscriber callback receives the raw message bytes.
MessageHandler = Callable[[bytes], None]


@runtime_checkable
class Transport(Protocol):
    """The minimal transport contract the bus depends on."""

    @property
    def connected(self) -> bool: ...

    def connect(self) -> None: ...

    def publish(self, subject: str, data: bytes) -> None: ...

    def subscribe(self, subject: str, handler: MessageHandler) -> None: ...

    def close(self) -> None: ...


class InProcessTransport:
    """An in-memory pub/sub transport (synchronous fan-out).

    Publishing delivers the message immediately to every subscriber registered
    for the subject. Handler exceptions are swallowed and logged so one bad
    subscriber can never break the publisher (matching real broker semantics).
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("watertwin.events.inprocess")
        self._subscribers: dict[str, list[MessageHandler]] = {}
        self._lock = threading.RLock()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True

    def publish(self, subject: str, data: bytes) -> None:
        if not self._connected:
            raise RuntimeError("InProcessTransport is not connected")
        with self._lock:
            handlers = list(self._subscribers.get(subject, ()))
        for handler in handlers:
            try:
                handler(data)
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.warning("in-process subscriber failed for %s: %s", subject, exc)

    def subscribe(self, subject: str, handler: MessageHandler) -> None:
        with self._lock:
            self._subscribers.setdefault(subject, []).append(handler)

    def close(self) -> None:
        with self._lock:
            self._subscribers.clear()
        self._connected = False


class NatsTransport:
    """Real NATS transport backed by ``nats-py`` on a background event loop.

    The async NATS client is driven from a dedicated daemon thread running its
    own asyncio loop; synchronous ``publish``/``subscribe`` calls are marshalled
    onto that loop with a bounded timeout. Any failure (``nats-py`` absent,
    broker unreachable, publish timeout) surfaces as an exception so the bus can
    fall back to direct delivery.
    """

    def __init__(
        self,
        url: str,
        *,
        connect_timeout: float = 2.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._url = url
        self._connect_timeout = connect_timeout
        self._logger = logger or logging.getLogger("watertwin.events.nats")
        self._loop = None
        self._thread: threading.Thread | None = None
        self._nc = None
        self._connected = False

    @property
    def connected(self) -> bool:
        nc = self._nc
        return bool(self._connected and nc is not None and nc.is_connected)

    def connect(self) -> None:
        import asyncio

        try:
            import nats  # noqa: F401
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "nats-py is not installed; cannot use the NATS transport"
            ) from exc

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="watertwin-nats-eventbus",
            daemon=True,
        )
        self._thread.start()

        future = asyncio.run_coroutine_threadsafe(self._async_connect(), self._loop)
        try:
            # Allow a little slack beyond the client's own connect timeout.
            self._nc = future.result(timeout=self._connect_timeout + 2.0)
        except Exception:
            # Clean up the background loop/thread so a failed connect leaves no
            # dangling task, then let the bus degrade gracefully.
            self._teardown_loop()
            raise
        self._connected = True
        self._logger.info("connected to NATS at %s", self._url)

    def _teardown_loop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._loop = None
        self._thread = None
        self._nc = None
        self._connected = False

    def _run_loop(self) -> None:
        import asyncio

        loop = self._loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        finally:
            # Cancel any still-pending tasks (e.g. an in-flight connect that we
            # gave up on) and close the loop cleanly so no task is orphaned.
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.close()

    async def _async_connect(self):
        import nats

        return await nats.connect(
            self._url,
            connect_timeout=self._connect_timeout,
            allow_reconnect=True,
            max_reconnect_attempts=-1,
        )

    def publish(self, subject: str, data: bytes) -> None:
        import asyncio

        if self._nc is None or self._loop is None:
            raise RuntimeError("NATS transport is not connected")
        future = asyncio.run_coroutine_threadsafe(
            self._nc.publish(subject, data), self._loop
        )
        future.result(timeout=self._connect_timeout)

    def subscribe(self, subject: str, handler: MessageHandler) -> None:
        import asyncio

        if self._nc is None or self._loop is None:
            raise RuntimeError("NATS transport is not connected")

        async def _cb(msg) -> None:
            try:
                handler(msg.data)
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.warning("NATS subscriber failed for %s: %s", subject, exc)

        future = asyncio.run_coroutine_threadsafe(
            self._nc.subscribe(subject, cb=_cb), self._loop
        )
        future.result(timeout=self._connect_timeout)

    def close(self) -> None:
        import asyncio
        import contextlib

        if self._nc is not None and self._loop is not None:
            with contextlib.suppress(Exception):  # pragma: no cover - best-effort drain
                asyncio.run_coroutine_threadsafe(self._nc.drain(), self._loop).result(
                    timeout=2.0
                )
        self._teardown_loop()
