"""Unit tests for the shared watertwin_observability package.

Covers the two acceptance criteria at the toolkit level (independent of any one
service): log lines are valid JSON carrying a correlation id, and ``/metrics``
renders the expected Prometheus series. Also exercises the correlation-id
propagation through the pure-ASGI middleware.
"""

from __future__ import annotations

import asyncio
import json
import logging

from watertwin_observability import (
    CORRELATION_ID_HEADER,
    REQUEST_COUNT,
    JsonLogFormatter,
    ObservabilityMiddleware,
    configure_logging,
    get_correlation_id,
    render_metrics,
    reset_correlation_id,
    set_correlation_id,
    set_service_info,
)


def _format_one(record_kwargs: dict) -> dict:
    formatter = JsonLogFormatter("pkg-test")
    logger = logging.getLogger("pkg.formatter.test")
    record = logger.makeRecord(**record_kwargs)
    return json.loads(formatter.format(record))


def test_log_line_is_valid_json_with_correlation_id():
    token = set_correlation_id("cid-log-1")
    try:
        obj = _format_one(
            {
                "name": "pkg.test",
                "level": logging.INFO,
                "fn": "f",
                "lno": 1,
                "msg": "ingest ok",
                "args": (),
                "exc_info": None,
                "extra": {"lag_seconds": 0.5},
            }
        )
    finally:
        reset_correlation_id(token)

    assert obj["correlation_id"] == "cid-log-1"
    assert obj["service"] == "pkg-test"
    assert obj["level"] == "INFO"
    assert obj["message"] == "ingest ok"
    assert obj["logger"] == "pkg.test"
    assert obj["lag_seconds"] == 0.5
    assert "timestamp" in obj


def test_log_line_without_correlation_id_omits_field():
    obj = _format_one(
        {
            "name": "pkg.test",
            "level": logging.WARNING,
            "fn": "f",
            "lno": 1,
            "msg": "no context",
            "args": (),
            "exc_info": None,
        }
    )
    assert "correlation_id" not in obj
    assert obj["level"] == "WARNING"


def test_configure_logging_is_idempotent():
    configure_logging("pkg-test")
    configure_logging("pkg-test")
    root = logging.getLogger()
    json_handlers = [h for h in root.handlers if isinstance(h.formatter, JsonLogFormatter)]
    assert len(json_handlers) == 1


def test_render_metrics_exposes_expected_series():
    set_service_info("pkg-test", "9.9.9")
    REQUEST_COUNT.labels(
        service="pkg-test", method="GET", path="/probe", status="200"
    ).inc()
    body, content_type = render_metrics()
    text = body.decode()
    assert "text/plain" in content_type
    assert "http_requests_total" in text
    assert "http_request_duration_seconds" in text
    assert "watertwin_service_info" in text
    assert 'service="pkg-test"' in text


def test_middleware_propagates_and_echoes_correlation_id():
    seen: dict[str, object] = {}
    sent: list[dict] = []

    async def downstream(scope, receive, send):
        seen["cid"] = get_correlation_id()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    async def drive(headers):
        mw = ObservabilityMiddleware(downstream, "pkg-test")
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/probe",
            "headers": headers,
        }
        await mw(scope, receive, send)

    asyncio.run(drive([(b"x-correlation-id", b"cid-mw-1")]))
    assert seen["cid"] == "cid-mw-1"
    start = next(m for m in sent if m["type"] == "http.response.start")
    header_name = CORRELATION_ID_HEADER.lower().encode()
    assert (header_name, b"cid-mw-1") in start["headers"]

    # Absent inbound header -> a correlation id is minted.
    seen.clear()
    sent.clear()
    asyncio.run(drive([]))
    assert seen["cid"] and len(str(seen["cid"])) >= 16


def test_middleware_clears_correlation_id_after_request():
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    async def drive():
        mw = ObservabilityMiddleware(downstream, "pkg-test")
        scope = {"type": "http", "method": "GET", "path": "/probe", "headers": []}
        await mw(scope, receive, send)

    asyncio.run(drive())
    assert get_correlation_id() is None
