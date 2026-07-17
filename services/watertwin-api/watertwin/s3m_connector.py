"""Connector to the S3M-Core quad-engine, with a graceful local fallback.

The connector adapts a :class:`~watertwin.schemas.WaterTwinPacket` into the S3M-Core
``OperationalPacket`` shape and submits it to the quad-engine. If S3M-Core is
unreachable for *any* reason (timeout, connection error, non-2xx response, or an
unusable body), :meth:`S3MConnector.submit` returns a locally-computed fallback card
instead of raising, so the WaterTwin keeps producing operator guidance offline.

The advisory control boundary is preserved on every path: cards returned from either
S3M-Core or the local fallback always carry ``control_write_enabled=False``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from .recommendations import assess_hpp
from .schemas import (
    DEFAULT_REQUESTED_OUTPUTS,
    ApprovalStatus,
    OperationalPacket,
    PacketType,
    RankedCause,
    RecommendationCard,
    WaterTwinPacket,
)

logger = logging.getLogger("watertwin.s3m_connector")

_PACKET_ENDPOINT = "/api/quad-engine/packet"
_STATUS_ENDPOINT = "/api/quad-engine/status"


class S3MConnector:
    """Client for the S3M-Core quad-engine with local-fallback resilience."""

    def __init__(
        self,
        core_url: str = "http://localhost:8081",
        *,
        timeout: float = 5.0,
        facility_id: str = "facility-unknown",
        train_id: str = "train-unknown",
        client: httpx.Client | None = None,
    ) -> None:
        self.core_url = core_url.rstrip("/")
        self.timeout = timeout
        self.facility_id = facility_id
        self.train_id = train_id
        self._client = client

    # -- packet construction -------------------------------------------------

    def build_packet(
        self,
        asset: Any,
        telemetry: dict[str, Any],
        anomaly: dict[str, Any] | None = None,
        *,
        facility_id: str | None = None,
        train_id: str | None = None,
    ) -> WaterTwinPacket:
        """Build a :class:`WaterTwinPacket` from asset context and telemetry.

        A water anomaly promotes the packet to ``packet_type="alert"``; otherwise it
        is a routine packet. The canonical set of quad-engine outputs is requested.
        """
        asset_id = self._asset_id_of(asset)
        packet_type = PacketType.ALERT if anomaly else PacketType.ROUTINE

        return WaterTwinPacket(
            packet_type=packet_type,
            facility_id=facility_id or self.facility_id,
            train_id=train_id or self.train_id,
            asset_id=asset_id,
            domain="water",
            telemetry=dict(telemetry or {}),
            anomaly=dict(anomaly or {}),
            requested_outputs=list(DEFAULT_REQUESTED_OUTPUTS),
            control_write_enabled=False,
        )

    def _to_core_packet(self, pkt: WaterTwinPacket) -> OperationalPacket:
        """Adapt a :class:`WaterTwinPacket` into an S3M-Core ``OperationalPacket``.

        The water domain and all water-specific fields are preserved inside the
        ``payload`` so the quad-engine retains full context.
        """
        payload: dict[str, Any] = {
            "domain": pkt.domain,
            "facility_id": pkt.facility_id,
            "train_id": pkt.train_id,
            "asset_id": pkt.asset_id,
            "telemetry": pkt.telemetry,
            "anomaly": pkt.anomaly,
        }
        return OperationalPacket(
            packet_type=pkt.packet_type.value,
            source="watertwin",
            requested_outputs=list(pkt.requested_outputs),
            payload=payload,
            ts=pkt.ts,
            control_write_enabled=False,
        )

    # -- submission ----------------------------------------------------------

    def submit(self, pkt: WaterTwinPacket) -> RecommendationCard:
        """Submit a packet to S3M-Core, returning a recommendation card.

        On any failure the locally-computed fallback card is returned instead of
        raising. The control boundary (``control_write_enabled=False``) is enforced
        on both the S3M-Core and fallback paths.
        """
        core_packet = self._to_core_packet(pkt)
        url = f"{self.core_url}{_PACKET_ENDPOINT}"
        try:
            data = self._post_json(url, core_packet.model_dump(mode="json"))
            cards = data.get("decision_cards") if isinstance(data, dict) else None
            if not cards:
                logger.warning(
                    "S3M-Core returned no decision cards; using local fallback",
                    extra={"asset_id": pkt.asset_id},
                )
                return self._fallback_card(pkt)
            return self._map_decision_card(pkt, cards[0])
        except Exception as exc:
            logger.warning(
                "S3M-Core submit failed; using local fallback",
                extra={"asset_id": pkt.asset_id, "error": str(exc)},
            )
            return self._fallback_card(pkt)

    def _post_json(self, url: str, body: dict[str, Any]) -> Any:
        if self._client is not None:
            resp = self._client.post(url, json=body, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()

    def _map_decision_card(
        self, pkt: WaterTwinPacket, card: dict[str, Any]
    ) -> RecommendationCard:
        """Map an S3M-Core decision card into a :class:`RecommendationCard`."""
        ranked = [
            RankedCause(
                cause=str(rc.get("cause", "unknown")),
                probability=float(rc.get("probability", 0.0)),
                evidence=list(rc.get("evidence", []) or []),
            )
            for rc in (card.get("ranked_causes") or [])
            if isinstance(rc, dict)
        ]
        actions = card.get("recommended_actions") or []
        if isinstance(actions, str):
            actions = [actions]

        return RecommendationCard(
            recommendation_id=str(
                card.get("recommendation_id") or card.get("id") or uuid.uuid4()
            ),
            asset_id=pkt.asset_id,
            title=str(card.get("title", "S3M-Core recommendation")),
            summary=str(card.get("summary", card.get("operational_summary", ""))),
            root_cause=str(card.get("root_cause", card.get("root_cause_analysis", ""))),
            ranked_causes=ranked,
            recommended_actions=[str(a) for a in actions],
            operator_explanation=str(card.get("operator_explanation", "")),
            confidence=float(card.get("confidence", 0.0) or 0.0),
            approval_status=ApprovalStatus.PENDING,
            source_engine_status="core",
            control_write_enabled=False,
        )

    def _fallback_card(self, pkt: WaterTwinPacket) -> RecommendationCard:
        """Build a recommendation card from local engineering analysis.

        Used whenever S3M-Core cannot be reached or produced nothing usable.
        """
        asset = {
            "asset_id": pkt.asset_id,
            "facility_id": pkt.facility_id,
            "train_id": pkt.train_id,
        }
        assessment = assess_hpp(asset, pkt.telemetry)

        summary = (
            f"Local analysis of {pkt.asset_id}: leading cause '{assessment.top_cause}' "
            f"(p={assessment.ranked_causes[0].probability:.2f})."
            if assessment.ranked_causes
            else f"Local analysis of {pkt.asset_id}."
        )

        return RecommendationCard(
            recommendation_id=str(uuid.uuid4()),
            asset_id=pkt.asset_id,
            title=f"Fallback advisory for {pkt.asset_id}",
            summary=summary,
            root_cause=assessment.top_cause,
            ranked_causes=assessment.ranked_causes,
            recommended_actions=[assessment.recommended_action],
            operator_explanation=(
                "S3M-Core was unavailable; this card was generated by the WaterTwin's "
                "local physics-informed analysis. It is advisory only."
            ),
            confidence=assessment.confidence,
            approval_status=ApprovalStatus.PENDING,
            source_engine_status="fallback_local",
            evidence=assessment.evidence,
            control_write_enabled=False,
        )

    # -- status --------------------------------------------------------------

    def core_status(self) -> dict[str, Any]:
        """Best-effort query of the quad-engine status endpoint.

        Never raises: on any failure it reports the engine as unreachable.
        """
        url = f"{self.core_url}{_STATUS_ENDPOINT}"
        try:
            if self._client is not None:
                resp = self._client.get(url, timeout=self.timeout)
            else:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    return {"reachable": True, "status": resp.json()}
            resp.raise_for_status()
            return {"reachable": True, "status": resp.json()}
        except Exception as exc:
            logger.info("S3M-Core status unreachable", extra={"error": str(exc)})
            return {"reachable": False, "error": str(exc)}

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _asset_id_of(asset: Any) -> str:
        if isinstance(asset, dict):
            return str(asset.get("asset_id") or asset.get("id") or "unknown-hpp")
        return str(
            getattr(asset, "asset_id", None) or getattr(asset, "id", None) or "unknown-hpp"
        )
