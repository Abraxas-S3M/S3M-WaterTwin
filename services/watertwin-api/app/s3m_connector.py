"""S3M-Core connector: submit a WaterTwinPacket to the quad-engine, with a
grounded local fallback (advisory, read-only).

WaterTwin is the *conductor*, not the physics engine: it assembles a
:class:`~canonical_water_model.WaterTwinPacket` from the platform's already-
computed layer outputs + retrieved documents and submits it to the S3M-Core
Quad-Engine Orchestration layer (see ``docs/architecture/s3m-core-contract.md``)
for reasoning/orchestration. S3M-Core is a *separate* upstream repository; when
it is not configured or not reachable, the connector raises
:class:`S3mCoreUnavailable` so the caller can fall back to a grounded, locally-
assembled answer (``source_engine_status = "fallback_local"``). The local
fallback is preserved by design -- the assistant is always grounded in platform
data + documents whether or not S3M-Core is present.

This connector performs no control write. It only submits an advisory packet and
reads back a structured result.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from canonical_water_model import WaterTwinPacket

#: Base URL of the S3M-Core service. Unset by default: S3M-Core is a separate
#: upstream repository, so the platform defaults to the grounded local fallback
#: until an operator wires a reachable quad-engine endpoint.
S3M_CORE_URL = os.environ.get("S3M_CORE_URL") or None

#: Quad-engine packet-submission path (per the S3M-Core contract).
_PACKET_PATH = "/api/quad-engine/packet"

#: Marker used everywhere a grounded local answer was produced without S3M-Core.
FALLBACK_LOCAL = "fallback_local"


class S3mCoreUnavailable(Exception):
    """Raised when S3M-Core is not configured or cannot be reached."""


@dataclass
class ConnectorResult:
    """The result of submitting a packet to S3M-Core (advisory orchestration)."""

    source_engine_status: str
    outputs: dict[str, Any] = field(default_factory=dict)
    engine_status: dict[str, str] = field(default_factory=dict)
    confidence: float | None = None
    result_id: str | None = None
    human_review_required: bool = True


class S3mConnector:
    """Submits advisory packets to the S3M-Core quad-engine (read-only)."""

    def __init__(self, base_url: str | None = S3M_CORE_URL, timeout: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return self.base_url is not None

    def submit_packet(self, packet: WaterTwinPacket) -> ConnectorResult:
        """Submit ``packet`` to S3M-Core; raise :class:`S3mCoreUnavailable` if it
        is not configured or not reachable.

        On success returns a :class:`ConnectorResult` describing the quad-engine
        orchestration. The caller assembles the grounded answer text from the
        same platform context regardless, so an answer is never free-form.
        """
        if not self.base_url:
            raise S3mCoreUnavailable("S3M-Core URL is not configured (S3M_CORE_URL unset)")
        try:
            import httpx

            body = {
                "packet_id": packet.packet_id,
                "source": packet.source,
                "track": packet.track,
                "packet_type": "decision_request",
                "payload": packet.payload,
                "requested_outputs": packet.requested_outputs,
            }
            resp = httpx.post(
                f"{self.base_url}{_PACKET_PATH}", json=body, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except S3mCoreUnavailable:
            raise
        except Exception as exc:  # network / HTTP / decode failure -> fallback
            raise S3mCoreUnavailable(f"S3M-Core unreachable: {exc}") from exc

        return ConnectorResult(
            source_engine_status="quad-engine",
            outputs=data.get("outputs", {}) or {},
            engine_status=data.get("engine_status", {}) or {},
            confidence=data.get("confidence"),
            result_id=data.get("result_id"),
            human_review_required=bool(data.get("human_review_required", True)),
        )


#: Process-wide default connector (local fallback unless S3M_CORE_URL is set).
_connector: S3mConnector | None = None


def get_connector() -> S3mConnector:
    global _connector
    if _connector is None:
        _connector = S3mConnector()
    return _connector
