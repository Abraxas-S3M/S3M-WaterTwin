"""In-memory ring buffer for recent log records.

Support bundles include a tail of recent application logs. Rather than depend
on a file path or a container log driver, the service keeps the most recent log
lines in a bounded, thread-safe in-memory ring buffer. The buffer holds only
advisory operational logs; secret values are additionally scrubbed when a
bundle is generated (see ``support.py``).
"""

from __future__ import annotations

import logging
import threading
from collections import deque

DEFAULT_CAPACITY = 2000


class RingBufferHandler(logging.Handler):
    """Logging handler that retains the last ``capacity`` formatted records."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:  # pragma: no cover - never let logging crash callers
            return
        with self._lock:
            self._buffer.append(line)

    def lines(self) -> list[str]:
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()


# Process-wide handler instance.
_handler = RingBufferHandler()
_installed = False
_install_lock = threading.Lock()


def install(logger_name: str = "watertwin", level: int = logging.INFO) -> RingBufferHandler:
    """Attach the ring buffer handler to ``logger_name`` (idempotent)."""
    global _installed
    with _install_lock:
        logger = logging.getLogger(logger_name)
        if level < logger.level or logger.level == logging.NOTSET:
            logger.setLevel(level)
        if not _installed:
            logger.addHandler(_handler)
            _installed = True
    return _handler


def recent_lines() -> list[str]:
    return _handler.lines()


def clear() -> None:
    _handler.clear()
