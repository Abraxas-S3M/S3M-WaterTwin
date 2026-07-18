"""watertwin-ingest FastAPI app (advisory, read-only).

Exposes the analysis endpoint for staged uploads. This service holds no control
path of any kind: ``control_mode`` is advisory, operator approval is required,
and control writes are disabled. It never writes to SCADA/PLC/OPC UA/MQTT.
"""

from __future__ import annotations

from typing import Any

from canonical_water_model import ControlBoundary
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .analysis import analyze_upload
from .models import AnalysisResult, ParseResult

app = FastAPI(
    title="S3M-WaterTwin Ingest",
    version="0.1.0",
    description=(
        "Staged-file data intake with optional AI-assisted analysis. "
        "Advisory / read-only: analyzes, never commits; issues no control write."
    ),
)

#: The read-only boundary this whole service operates under.
CONTROL_BOUNDARY = ControlBoundary()


class AnalysisRequest(BaseModel):
    """Request body for the analysis endpoint."""

    parse_result: ParseResult
    approved_documents: list[dict[str, Any]] = Field(default_factory=list)
    requested_by: str | None = None


@app.get("/api/v1/ingest/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "control_boundary": CONTROL_BOUNDARY.model_dump(mode="json"),
    }


@app.post("/api/v1/ingest/uploads/{upload_id}/analysis", response_model=AnalysisResult)
def request_analysis(upload_id: str, body: AnalysisRequest) -> AnalysisResult:
    """Request AI-assisted analysis for a staged upload.

    Idempotent and cached by ``(ingest_id, parse_result_hash)`` so repeat requests
    do not re-bill or re-query. Degrades gracefully: if S3M-Core is unavailable the
    response has ``available=False`` and the caller renders the plain diff.
    """
    if body.parse_result.ingest_id != upload_id:
        raise HTTPException(
            status_code=400,
            detail="upload_id in the path does not match parse_result.ingest_id",
        )
    return analyze_upload(
        body.parse_result,
        body.approved_documents,
        requested_by=body.requested_by or "system",
    )
