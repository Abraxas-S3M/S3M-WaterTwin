"""S3M-Core analysis client (advisory, read-only).

Mirrors ``services/watertwin-api/app/s3m_connector.py``: S3M-Core is a *separate*
upstream repository. When it is not configured or not reachable, the client
raises :class:`S3mAnalysisUnavailable` so the caller can degrade gracefully and
render the plain diff with no analysis panel (analysis is never on the critical
path to a reviewable diff).

This client performs no control write and holds no database handle. It submits an
advisory analysis request (with the file body already wrapped in the delimited
untrusted-data block) and reads back a structured result.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

#: Base URL of the S3M-Core service. Unset by default: until an operator wires a
#: reachable endpoint, the ingest service degrades gracefully (no analysis).
S3M_CORE_URL = os.environ.get("S3M_CORE_URL") or None

#: Analysis-submission path (per the S3M-Core contract).
_ANALYSIS_PATH = "/api/quad-engine/analysis"

#: Marker used wherever analysis could not be produced via S3M-Core.
FALLBACK_LOCAL = "fallback_local"


class S3mAnalysisUnavailable(Exception):
    """Raised when S3M-Core is not configured, is slow, or errors."""


@dataclass
class AnalysisClientResult:
    """The raw structured result of an analysis submission to S3M-Core."""

    source_engine_status: str
    model_version: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)


class S3mAnalysisClient:
    """Submits advisory analysis requests to S3M-Core (read-only)."""

    def __init__(self, base_url: str | None = S3M_CORE_URL, timeout: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return self.base_url is not None

    def request_analysis(self, request_body: dict[str, Any]) -> AnalysisClientResult:
        """Submit ``request_body`` to S3M-Core; raise :class:`S3mAnalysisUnavailable`
        if it is not configured, unreachable, slow, or returns an error.

        The caller is responsible for having wrapped any file content in the
        delimited untrusted-data block before calling this.
        """
        if not self.base_url:
            raise S3mAnalysisUnavailable(
                "S3M-Core URL is not configured (S3M_CORE_URL unset)"
            )
        try:
            import httpx

            resp = httpx.post(
                f"{self.base_url}{_ANALYSIS_PATH}", json=request_body, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except S3mAnalysisUnavailable:
            raise
        except Exception as exc:  # network / HTTP / decode / timeout -> degrade
            raise S3mAnalysisUnavailable(f"S3M-Core unreachable: {exc}") from exc

        return AnalysisClientResult(
            source_engine_status="quad-engine",
            model_version=data.get("model_version"),
            outputs=data.get("outputs", {}) or {},
        )


#: Process-wide default client (degrades gracefully unless S3M_CORE_URL is set).
_client: S3mAnalysisClient | None = None


def get_analysis_client() -> S3mAnalysisClient:
    global _client
    if _client is None:
        _client = S3mAnalysisClient()
    return _client
