"""AI-assisted analysis of staged files (advisory, read-only, never commits).

Given a :class:`~app.models.ParseResult` plus the relevant approved documents,
this module asks S3M-Core for three things and turns them into typed, safety-
clamped structures:

* a plain-language **summary** of what the file contains;
* **anomaly flags** cross-checked against existing canonical config
  (e.g. "pump P-003's curve implies 18% higher duty than its nameplate");
* **drafted values** for fields the parser could not fill.

Each returned item carries a confidence in ``[0, 1]``, a rationale, and a citation
pointing at a specific source location.

Invariants enforced here, independent of anything the upstream returns:

* Drafted values become :class:`ProposedChange` rows via
  :meth:`ProposedChange.from_draft`, so they are ALWAYS ``ai_suggested=True`` and
  ``accepted=False`` on arrival. No branch in this module sets ``accepted=True``.
* An AI draft's provenance is clamped so it can never outrank the source file
  (:func:`app.models.clamp_ai_provenance`). Provenance from the upstream response
  is never trusted.
* All file content sent upstream is wrapped in the delimited untrusted-data block
  (:func:`app.untrusted.wrap_untrusted`); instruction-like text inside a file
  therefore cannot change our task, output, acceptance state, or provenance.
* If S3M-Core is unavailable/slow/errors, a degraded result
  (``available=False``) is returned so the plain diff still renders. Analysis is
  never on the critical path to a reviewable diff.
* Every request and response is written to the hash-chained audit log, including
  the model version, so an answer can be reconstructed later.
"""

from __future__ import annotations

from typing import Any

from .audit import (
    KIND_ANALYSIS_REQUEST,
    KIND_ANALYSIS_RESPONSE,
    AuditChain,
    get_audit_chain,
)
from .models import (
    AnalysisResult,
    AnalysisSummary,
    AnomalyFlag,
    DraftedValue,
    ParseResult,
    ProposedChange,
    SourceCitation,
)
from .s3m_client import (
    FALLBACK_LOCAL,
    AnalysisClientResult,
    S3mAnalysisClient,
    S3mAnalysisUnavailable,
    get_analysis_client,
)
from .untrusted import wrap_untrusted

REQUESTED_OUTPUTS = ["summary", "anomaly_flags", "drafted_values"]

_DEGRADED_NOTICE = (
    "AI analysis is temporarily unavailable. The proposal below is complete and "
    "reviewable without it."
)


class AnalysisCache:
    """Idempotency cache keyed by ``(ingest_id, parse_result_hash)``.

    Only *successful* (``available=True``) results are cached, so a degraded
    result never suppresses a later retry once S3M-Core is reachable again.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], AnalysisResult] = {}

    def get(self, ingest_id: str, parse_result_hash: str) -> AnalysisResult | None:
        return self._store.get((ingest_id, parse_result_hash))

    def put(self, result: AnalysisResult) -> None:
        if result.available:
            self._store[(result.ingest_id, result.parse_result_hash)] = result


#: Process-wide default cache for the analysis endpoint.
_cache: AnalysisCache | None = None


def get_cache() -> AnalysisCache:
    global _cache
    if _cache is None:
        _cache = AnalysisCache()
    return _cache


def build_request(
    parse_result: ParseResult, approved_documents: list[dict[str, Any]]
) -> dict[str, Any]:
    """Assemble the advisory analysis request for S3M-Core.

    The file body is wrapped in the delimited untrusted-data block; nothing from
    the file is placed in an instruction position.
    """
    return {
        "ingest_id": parse_result.ingest_id,
        "parse_result_hash": parse_result.content_hash(),
        "source_filename": parse_result.source_filename,
        "content_type": parse_result.content_type,
        "source_provenance": parse_result.source_provenance.value,
        "parsed_fields": [f.model_dump(mode="json") for f in parse_result.parsed_fields],
        "unparsed_fields": list(parse_result.unparsed_fields),
        "approved_documents": approved_documents,
        "untrusted_file_data": wrap_untrusted(parse_result.content),
        "requested_outputs": REQUESTED_OUTPUTS,
    }


def _default_citation(parse_result: ParseResult) -> SourceCitation:
    return SourceCitation(
        document_id=parse_result.ingest_id,
        locator=f"{parse_result.source_filename} (unspecified location)",
    )


def _coerce_citation(raw: Any, parse_result: ParseResult) -> SourceCitation:
    """Coerce an upstream citation into a :class:`SourceCitation`.

    Every item must be cited; when the upstream omits a usable citation we fall
    back to a file-level citation rather than leaving an item uncited.
    """
    if isinstance(raw, dict) and raw.get("document_id") and raw.get("locator"):
        return SourceCitation(
            document_id=str(raw["document_id"]),
            locator=str(raw["locator"]),
            snippet=(str(raw["snippet"]) if raw.get("snippet") is not None else None),
        )
    return _default_citation(parse_result)


def _clamp_confidence(raw: Any, default: float = 0.5) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, value))


def _parse_summary(
    outputs: dict[str, Any], parse_result: ParseResult
) -> AnalysisSummary | None:
    raw = outputs.get("summary")
    if not isinstance(raw, dict) or not raw.get("text"):
        return None
    return AnalysisSummary(
        text=str(raw["text"]),
        confidence=_clamp_confidence(raw.get("confidence")),
        rationale=str(raw.get("rationale") or "No rationale supplied."),
        citation=_coerce_citation(raw.get("citation"), parse_result),
    )


def _parse_anomalies(
    outputs: dict[str, Any], parse_result: ParseResult
) -> list[AnomalyFlag]:
    flags: list[AnomalyFlag] = []
    for index, raw in enumerate(outputs.get("anomaly_flags") or []):
        if not isinstance(raw, dict) or not raw.get("message"):
            continue
        cross_refs = raw.get("cross_references") or []
        flags.append(
            AnomalyFlag(
                code=str(raw.get("code") or f"anomaly-{index + 1}"),
                message=str(raw["message"]),
                severity=str(raw.get("severity") or "info"),
                confidence=_clamp_confidence(raw.get("confidence")),
                rationale=str(raw.get("rationale") or "No rationale supplied."),
                citation=_coerce_citation(raw.get("citation"), parse_result),
                cross_references=[str(c) for c in cross_refs],
            )
        )
    return flags


def _parse_drafts(
    outputs: dict[str, Any], parse_result: ParseResult
) -> tuple[list[DraftedValue], list[ProposedChange]]:
    """Turn upstream drafted values into typed drafts + UNACCEPTED diff rows.

    A draft is only accepted for a field the parser actually left unparsed. The
    upstream's provenance and any acceptance/accepted hint it may include are
    ignored entirely: acceptance is forced to ``False`` and provenance is derived
    from (and clamped to) the source file.
    """
    drafts: list[DraftedValue] = []
    changes: list[ProposedChange] = []
    unparsed = set(parse_result.unparsed_fields)
    for index, raw in enumerate(outputs.get("drafted_values") or []):
        if not isinstance(raw, dict):
            continue
        field_path = str(raw.get("field_path") or "")
        if field_path not in unparsed:
            # The AI may only draft fields the parser could not fill.
            continue
        citation = _coerce_citation(raw.get("citation"), parse_result)
        confidence = _clamp_confidence(raw.get("confidence"))
        rationale = str(raw.get("rationale") or "No rationale supplied.")
        value = raw.get("value")
        drafts.append(
            DraftedValue(
                field_path=field_path,
                value=value,
                confidence=confidence,
                rationale=rationale,
                citation=citation,
            )
        )
        changes.append(
            ProposedChange.from_draft(
                change_id=f"{parse_result.ingest_id}:draft:{field_path}:{index}",
                field_path=field_path,
                proposed_value=value,
                ai_confidence=confidence,
                ai_rationale=rationale,
                citation=citation,
                source_provenance=parse_result.source_provenance,
            )
        )
    return drafts, changes


def _degraded_result(parse_result: ParseResult, parse_result_hash: str) -> AnalysisResult:
    return AnalysisResult(
        ingest_id=parse_result.ingest_id,
        parse_result_hash=parse_result_hash,
        available=False,
        notice=_DEGRADED_NOTICE,
        model_version=None,
        source_engine_status=FALLBACK_LOCAL,
    )


def analyze_upload(
    parse_result: ParseResult,
    approved_documents: list[dict[str, Any]] | None = None,
    *,
    client: S3mAnalysisClient | None = None,
    audit: AuditChain | None = None,
    cache: AnalysisCache | None = None,
    requested_by: str = "system",
) -> AnalysisResult:
    """Analyze one staged file, idempotently and with graceful degradation.

    Cached by ``(ingest_id, parse_result_hash)`` so a repeat request neither
    re-bills nor re-queries S3M-Core. On a cache hit no upstream call is made.
    On any S3M-Core failure a degraded (``available=False``) result is returned
    and the caller still renders the plain diff.
    """
    approved_documents = approved_documents or []
    client = client or get_analysis_client()
    audit = audit or get_audit_chain()
    cache = cache or get_cache()

    parse_result_hash = parse_result.content_hash()

    cached = cache.get(parse_result.ingest_id, parse_result_hash)

    audit.append(
        kind=KIND_ANALYSIS_REQUEST,
        actor=requested_by,
        subject=parse_result.ingest_id,
        payload={
            "ingest_id": parse_result.ingest_id,
            "parse_result_hash": parse_result_hash,
            "unparsed_fields": list(parse_result.unparsed_fields),
            "num_approved_documents": len(approved_documents),
            "untrusted_data_wrapped": True,
            "cache_hit": cached is not None,
        },
    )

    if cached is not None:
        audit.append(
            kind=KIND_ANALYSIS_RESPONSE,
            actor=requested_by,
            subject=parse_result.ingest_id,
            payload={
                "ingest_id": parse_result.ingest_id,
                "parse_result_hash": parse_result_hash,
                "model_version": cached.model_version,
                "source_engine_status": cached.source_engine_status,
                "available": cached.available,
                "cached": True,
                "num_anomalies": len(cached.anomalies),
                "num_drafts": len(cached.drafted_values),
            },
        )
        return cached

    request_body = build_request(parse_result, approved_documents)

    try:
        client_result: AnalysisClientResult = client.request_analysis(request_body)
    except S3mAnalysisUnavailable:
        degraded = _degraded_result(parse_result, parse_result_hash)
        audit.append(
            kind=KIND_ANALYSIS_RESPONSE,
            actor=requested_by,
            subject=parse_result.ingest_id,
            payload={
                "ingest_id": parse_result.ingest_id,
                "parse_result_hash": parse_result_hash,
                "model_version": None,
                "source_engine_status": degraded.source_engine_status,
                "available": False,
                "cached": False,
            },
        )
        return degraded

    outputs = client_result.outputs
    summary = _parse_summary(outputs, parse_result)
    anomalies = _parse_anomalies(outputs, parse_result)
    drafts, changes = _parse_drafts(outputs, parse_result)

    result = AnalysisResult(
        ingest_id=parse_result.ingest_id,
        parse_result_hash=parse_result_hash,
        available=True,
        notice=None,
        model_version=client_result.model_version,
        source_engine_status=client_result.source_engine_status,
        summary=summary,
        anomalies=anomalies,
        drafted_values=drafts,
        proposed_changes=changes,
    )

    cache.put(result)

    audit.append(
        kind=KIND_ANALYSIS_RESPONSE,
        actor=requested_by,
        subject=parse_result.ingest_id,
        payload={
            "ingest_id": parse_result.ingest_id,
            "parse_result_hash": parse_result_hash,
            "model_version": result.model_version,
            "source_engine_status": result.source_engine_status,
            "available": True,
            "cached": False,
            "num_anomalies": len(result.anomalies),
            "num_drafts": len(result.drafted_values),
            "all_changes_unaccepted": all(not c.accepted for c in result.proposed_changes),
        },
    )

    return result
