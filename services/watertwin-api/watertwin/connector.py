"""Connector to S3M-Core.

The connector posts an assembled *recommendation packet* to S3M-Core and returns
the recommendation payload. When S3M-Core is unreachable (e.g. running the twin
standalone, or in tests/CI) it transparently falls back to a local heuristic so
the service is always usable without external dependencies.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("watertwin.connector")


class S3MConnector:
    def __init__(self, base_url: str | None = None, timeout: float = 2.0) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout

    def health(self) -> bool:
        """Best-effort reachability check for S3M-Core."""

        if not self.base_url:
            return False
        try:
            resp = httpx.get(f"{self.base_url}/health", timeout=self.timeout)
            return resp.status_code < 500
        except httpx.HTTPError:
            return False

    def generate_recommendation(self, packet: dict[str, Any]) -> dict[str, Any]:
        """Return a recommendation payload for the given packet.

        Tries S3M-Core first; on any transport error falls back to a local
        heuristic. The returned dict always includes a ``source`` field.
        """

        if self.base_url:
            try:
                resp = httpx.post(
                    f"{self.base_url}/api/v1/recommendations/generate",
                    json=packet,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                data.setdefault("source", "s3m-core")
                return data
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(
                    "S3M-Core unavailable (%s); using local fallback recommender", exc
                )

        return self._local_fallback(packet)

    @staticmethod
    def _local_fallback(packet: dict[str, Any]) -> dict[str, Any]:
        asset = packet.get("asset", {})
        health = packet.get("health", {})
        anomaly = packet.get("anomaly", {})
        asset_name = asset.get("name", asset.get("id", "asset"))
        asset_type = asset.get("asset_type", "asset")
        status = health.get("status", "healthy")
        score = health.get("score", 100.0)
        is_anomaly = bool(anomaly.get("is_anomaly", False))

        severity_map = {
            "critical": "critical",
            "degraded": "high",
            "watch": "medium",
            "healthy": "low",
        }
        severity = severity_map.get(status, "low")
        if is_anomaly and severity in ("low", "medium"):
            severity = "high"

        actions: list[str] = []
        if status in ("degraded", "critical"):
            actions.append(f"Schedule inspection of {asset_name}")
            actions.append("Review recent maintenance history and trend data")
        if is_anomaly:
            metric = anomaly.get("metric", "a monitored metric")
            actions.append(f"Investigate anomalous {metric} reading")
        if not actions:
            actions.append("Continue routine monitoring; no action required")

        worst_factors = sorted(
            (health.get("factors") or {}).items(), key=lambda kv: kv[1]
        )[:2]
        factor_note = (
            ", ".join(f"{k} at {v:.0%} of nominal" for k, v in worst_factors)
            if worst_factors
            else "all monitored factors nominal"
        )

        title = f"{status.title()} condition on {asset_name}"
        summary = (
            f"{asset_name} ({asset_type}) health score is {score:.0f} "
            f"({status}). {'Anomaly detected. ' if is_anomaly else ''}"
            f"Advisory recommendation only."
        )
        rationale = (
            f"Health scoring against configured thresholds yields {score:.0f}/100. "
            f"Key factors: {factor_note}."
        )

        return {
            "source": "local-fallback",
            "title": title,
            "summary": summary,
            "rationale": rationale,
            "severity": severity,
            "recommended_actions": actions,
        }
