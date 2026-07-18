"""Client for watertwin-api's EXISTING configuration lifecycle.

The ingest service NEVER implements its own approval system. It creates and
publishes drafts through watertwin-api's per-entity endpoints
(``POST /api/v1/config/{entity}``, ``.../publish``, ``.../approve``) so every
change flows through the one audited draft -> submitted -> approved -> active
lifecycle.

Two implementations are provided:

* :class:`HttpConfigClient` — the production path; talks to watertwin-api.
* :class:`InMemoryConfigClient` — a faithful, dependency-free stand-in used for
  local runs and tests, mirroring the same lifecycle/versioning semantics.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol


class ConfigError(Exception):
    """Raised when the configuration lifecycle rejects an operation."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ConfigLifecycleClient(Protocol):
    def create_and_submit(
        self, entity: str, config_id: str, payload: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        """Create a draft and publish it (draft -> submitted). Returns the version."""
        ...

    def approve(self, entity: str, config_id: str, actor: str) -> dict[str, Any]:
        """Approve + activate a submitted version. Returns the version."""
        ...

    def active_config_ids(self, entity: str) -> set[str]:
        """The config ids that already have an active version (for diffing)."""
        ...


class InMemoryConfigClient:
    """In-memory lifecycle used for local runs and tests."""

    def __init__(self) -> None:
        # (entity, config_id) -> list of version records (oldest first).
        self._versions: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def create_and_submit(
        self, entity: str, config_id: str, payload: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        history = self._versions.setdefault((entity, config_id), [])
        version_no = len(history) + 1
        record = {
            "entity": entity,
            "config_id": config_id,
            "version": version_no,
            "version_id": str(uuid.uuid4()),
            "status": "submitted",
            "payload": payload,
            "submitted_by": actor,
            "approved_by": None,
        }
        history.append(record)
        return record

    def approve(self, entity: str, config_id: str, actor: str) -> dict[str, Any]:
        history = self._versions.get((entity, config_id))
        if not history:
            raise ConfigError(404, f"no {entity} '{config_id}' to approve")
        record = history[-1]
        if record["status"] != "submitted":
            raise ConfigError(409, f"{entity} '{config_id}' is {record['status']}")
        record["status"] = "active"
        record["approved_by"] = actor
        return record

    def active_config_ids(self, entity: str) -> set[str]:
        return {
            cid
            for (ent, cid), history in self._versions.items()
            if ent == entity and any(v["status"] == "active" for v in history)
        }


class HttpConfigClient:
    """Production lifecycle client that calls watertwin-api over HTTP."""

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        import httpx

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(f"{self._base}{path}", json=json, headers=self._headers())
        if resp.status_code >= 400:
            raise ConfigError(resp.status_code, resp.text)
        return resp.json()

    def create_and_submit(
        self, entity: str, config_id: str, payload: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        created = self._post(
            f"/api/v1/config/{entity}", {"payload": payload, "config_id": config_id}
        )
        cid = created.get("config_id", config_id)
        submitted = self._post(f"/api/v1/config/{entity}/{cid}/publish")
        return submitted

    def approve(self, entity: str, config_id: str, actor: str) -> dict[str, Any]:
        return self._post(f"/api/v1/config/{entity}/{config_id}/approve")

    def active_config_ids(self, entity: str) -> set[str]:
        import httpx

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(f"{self._base}/api/v1/config/{entity}", headers=self._headers())
        if resp.status_code >= 400:
            return set()
        items = resp.json().get("items", [])
        return {item.get("config_id") for item in items if item.get("config_id")}
