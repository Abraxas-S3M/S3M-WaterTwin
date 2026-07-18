"""Test doubles for the S3M-Core analysis client + shared parse-result fixtures."""

from __future__ import annotations

from typing import Any

from canonical_water_model import DataProvenance

from app.models import ParsedField, ParseResult, SourceCitation
from app.s3m_client import AnalysisClientResult, S3mAnalysisUnavailable

MODEL_VERSION = "s3m-core-analysis@2026.07.1"


class FakeAnalysisClient:
    """A configured client that returns canned outputs and counts calls."""

    def __init__(
        self, outputs: dict[str, Any], model_version: str = MODEL_VERSION
    ) -> None:
        self.outputs = outputs
        self.model_version = model_version
        self.calls = 0
        self.last_request: dict[str, Any] | None = None

    def request_analysis(self, request_body: dict[str, Any]) -> AnalysisClientResult:
        self.calls += 1
        self.last_request = request_body
        return AnalysisClientResult(
            source_engine_status="quad-engine",
            model_version=self.model_version,
            outputs=self.outputs,
        )


class UnavailableClient:
    """A client that always fails, simulating S3M-Core being down/slow/erroring."""

    def __init__(self) -> None:
        self.calls = 0

    def request_analysis(self, request_body: dict[str, Any]) -> AnalysisClientResult:
        self.calls += 1
        raise S3mAnalysisUnavailable("S3M-Core is down for this test")


def pump_curve_parse_result(
    source_provenance: DataProvenance = DataProvenance.measured,
    content: str | None = None,
) -> ParseResult:
    """A staged pump-curve upload with two fields the parser could not fill."""
    if content is None:
        content = (
            "flow_m3h,head_m\n"
            "0,120\n"
            "50,110\n"
            "100,95\n"
            "# nameplate: rated duty 100 m3/h @ 90 m (P-003)\n"
        )
    return ParseResult(
        ingest_id="ING-001",
        source_filename="P-003_pump_curve.csv",
        content_type="text/csv",
        source_provenance=source_provenance,
        content=content,
        parsed_fields=[
            ParsedField(
                field_path="pump.P-003.curve",
                value=[[0, 120], [50, 110], [100, 95]],
                citation=SourceCitation(document_id="ING-001", locator="rows 2-4"),
            )
        ],
        unparsed_fields=[
            "pump.P-003.rated_efficiency_pct",
            "pump.P-003.motor_frame",
        ],
    )


def pump_curve_outputs() -> dict[str, Any]:
    """A well-formed analysis payload for the pump-curve upload.

    Includes the acceptance-criteria anomaly: a curve that implies a higher duty
    than the nameplate.
    """
    citation = {"document_id": "ING-001", "locator": "row 4 (curve) vs nameplate note"}
    return {
        "summary": {
            "text": "Head-flow pump curve for P-003 with three operating points.",
            "confidence": 0.8,
            "rationale": "Parsed a 3-point head/flow table plus a nameplate note.",
            "citation": {"document_id": "ING-001", "locator": "rows 2-5"},
        },
        "anomaly_flags": [
            {
                "code": "curve-vs-nameplate",
                "message": "pump P-003's curve implies 18% higher duty than its nameplate",
                "severity": "warning",
                "confidence": 0.72,
                "rationale": (
                    "Head at rated flow (95 m @ 100 m3/h) exceeds the nameplate "
                    "duty point (90 m) by ~18% of implied hydraulic power."
                ),
                "citation": citation,
                "cross_references": ["AST-HPP-03"],
            }
        ],
        "drafted_values": [
            {
                "field_path": "pump.P-003.rated_efficiency_pct",
                "value": 78.0,
                "confidence": 0.55,
                "rationale": "Inferred from the curve shape near best-efficiency point.",
                "citation": {"document_id": "ING-001", "locator": "rows 2-4"},
            }
        ],
    }
