"""Correlation-id propagation for the WaterTwin services.

A correlation id ties together every log line, metric exemplar and trace span
produced while handling a single request. It is read from an inbound
``X-Correlation-ID`` (or ``X-Request-ID``) header when present, otherwise a new
one is minted, and it is always echoed back on the response so a caller can
correlate a request end-to-end across services.

The current correlation id lives in a :class:`contextvars.ContextVar` so it is
naturally scoped to the request that set it (including across ``await`` points)
without threading it through every function signature.
"""

from __future__ import annotations

import contextlib
import contextvars
import uuid

#: Canonical inbound/outbound header carrying the correlation id.
CORRELATION_ID_HEADER = "X-Correlation-ID"

#: Alternative inbound header honoured for interoperability with upstream
#: proxies / gateways that stamp an ``X-Request-ID``.
REQUEST_ID_HEADER = "X-Request-ID"

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "watertwin_correlation_id", default=None
)


def new_correlation_id() -> str:
    """Return a fresh, URL-safe correlation id."""
    return uuid.uuid4().hex


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current context, if any."""
    return _correlation_id.get()


def set_correlation_id(value: str) -> contextvars.Token:
    """Bind ``value`` as the current correlation id, returning a reset token."""
    return _correlation_id.set(value)


def reset_correlation_id(token: contextvars.Token) -> None:
    """Restore the correlation id captured by ``token`` (see :func:`set_correlation_id`)."""
    # A token can only be reset in the context that created it; ignore misuse.
    with contextlib.suppress(ValueError, LookupError):
        _correlation_id.reset(token)
