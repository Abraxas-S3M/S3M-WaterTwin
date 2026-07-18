"""Hash-chained audit entries posted to watertwin-api over HTTP.

The ingest service has **no direct database access**. It records every
auditable action (file received, status transition, soft delete) by producing a
tamper-evident, hash-chained audit entry and posting it to watertwin-api's audit
endpoint over the same authenticated HTTP API a human uses.

The chain format is **identical** to watertwin-api's server-side scheme
(``services/watertwin-api/app/audit.py``): ``hash = sha256(prev_hash +
canonical(event_core))`` over the canonical (sorted-key, compact) JSON of the
event's identity-bearing fields. This module deliberately reuses that exact
format rather than inventing a second audit scheme.

Transports are pluggable: an :class:`HttpAuditTransport` posts to the API in
production; an :class:`InMemoryAuditTransport` keeps entries in-process for dev
and tests (and when no API service token is configured).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import httpx

from . import config

logger = logging.getLogger("watertwin.ingest.audit")

# --- Chain primitives (must match services/watertwin-api/app/audit.py) ------

#: The chain anchor. The first event's ``prev_hash`` is the genesis hash.
GENESIS_HASH = "0" * 64

#: Fields folded into the chain hash (``prev_hash`` / ``hash`` are derived).
_HASHED_FIELDS = ("id", "ts", "kind", "actor", "subject", "payload")


def canonical(payload: Any) -> str:
    """Deterministic JSON encoding used as hash material (sorted, compact)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _event_core(event: dict[str, Any]) -> dict[str, Any]:
    return {field: event.get(field) for field in _HASHED_FIELDS}


def compute_hash(prev_hash: str, event: dict[str, Any]) -> str:
    """Compute the chain hash for ``event`` given the previous event's hash."""
    material = f"{prev_hash}{canonical(_event_core(event))}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def link_event(event: dict[str, Any], prev_hash: str) -> dict[str, Any]:
    """Attach ``prev_hash`` and the derived ``hash`` to ``event`` in place."""
    event["prev_hash"] = prev_hash
    event["hash"] = compute_hash(prev_hash, event)
    return event


class AuditError(RuntimeError):
    """Raised when an audit entry could not be delivered (fail-safe)."""


# --- Transports -------------------------------------------------------------


class AuditTransport(ABC):
    """Where linked audit entries are delivered."""

    name: str

    @abstractmethod
    def send(self, entry: dict[str, Any]) -> None:
        """Deliver a fully-linked audit ``entry`` (raises :class:`AuditError`)."""


class InMemoryAuditTransport(AuditTransport):
    """Keeps entries in-process (dev / tests / no API token configured)."""

    name = "in-memory"

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def send(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)


class HttpAuditTransport(AuditTransport):
    """Posts linked audit entries to watertwin-api over authenticated HTTP."""

    name = "http"

    def __init__(
        self,
        *,
        base_url: str,
        path: str,
        token: str | None,
        timeout: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.path = path
        self.token = token
        self.timeout = timeout

    def send(self, entry: dict[str, Any]) -> None:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Ingest-Token"] = self.token
        url = f"{self.base_url}{self.path}"
        try:
            response = httpx.post(url, json=entry, headers=headers, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise AuditError(f"failed to post audit entry to {url}: {exc}") from exc
        if response.status_code >= 400:
            raise AuditError(
                f"audit endpoint {url} rejected the entry: HTTP {response.status_code}"
            )


class AuditClient:
    """Builds hash-chained audit entries and delivers them via a transport."""

    def __init__(self, transport: AuditTransport, *, source: str = config.SERVICE_NAME) -> None:
        self._transport = transport
        self._source = source
        self._head = GENESIS_HASH
        self._lock = threading.Lock()

    @property
    def transport(self) -> AuditTransport:
        return self._transport

    @property
    def head(self) -> str:
        """The current chain head (hash of the last recorded entry)."""
        return self._head

    def record(
        self,
        *,
        kind: str,
        actor: str,
        subject: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build, link, and deliver one audit entry; return the linked entry."""
        with self._lock:
            event: dict[str, Any] = {
                "id": str(uuid.uuid4()),
                "ts": datetime.now(UTC).isoformat(),
                "kind": kind,
                "actor": actor,
                "subject": subject,
                "payload": payload or {},
                "source": self._source,
            }
            link_event(event, self._head)
            self._transport.send(event)
            self._head = event["hash"]
            return event


def build_audit_client() -> AuditClient:
    """Construct the audit client from config (HTTP when a token is set)."""
    if config.API_TOKEN:
        transport: AuditTransport = HttpAuditTransport(
            base_url=config.API_BASE_URL,
            path=config.API_AUDIT_PATH,
            token=config.API_TOKEN,
            timeout=config.API_TIMEOUT_S,
        )
        logger.info(
            "audit transport: HTTP -> %s%s", config.API_BASE_URL, config.API_AUDIT_PATH
        )
    else:
        transport = InMemoryAuditTransport()
        logger.warning(
            "audit transport: IN-MEMORY (no INGEST_API_TOKEN configured). Audit "
            "entries are not forwarded to watertwin-api; set INGEST_API_TOKEN in a "
            "real deployment."
        )
    return AuditClient(transport)
