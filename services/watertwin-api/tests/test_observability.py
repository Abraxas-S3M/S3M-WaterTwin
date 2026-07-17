"""Observability tests for watertwin-api.

Assert that ``/metrics`` exposes the expected Prometheus series (HTTP request
latency/throughput plus the audit-chain-length, buffer-depth and ingest-lag
domain gauges) and that log lines are valid JSON carrying a correlation id.
"""

from __future__ import annotations

import io
import json
import logging

from fastapi.testclient import TestClient

from watertwin_observability import (
    CORRELATION_ID_HEADER,
    JsonLogFormatter,
    configure_logging,
    reset_correlation_id,
    set_correlation_id,
)

from app.main import app

EXPECTED_SERIES = (
    "http_requests_total",
    "http_request_duration_seconds",
    "http_requests_in_progress",
    "watertwin_audit_chain_length",
    "watertwin_buffer_depth",
    "watertwin_ingest_lag_seconds",
    "watertwin_service_info",
)


def test_metrics_exposes_expected_series():
    with TestClient(app) as client:
        client.get("/health")
        response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    for series in EXPECTED_SERIES:
        assert series in body, f"missing series: {series}"
    # Request metrics are labelled with this service and the matched route
    # template (not the raw path), keeping label cardinality bounded.
    assert 'service="watertwin-api"' in body
    assert 'path="/health"' in body


def test_correlation_id_is_echoed_when_supplied():
    with TestClient(app) as client:
        response = client.get("/health", headers={CORRELATION_ID_HEADER: "corr-abc-123"})
    assert response.headers.get(CORRELATION_ID_HEADER) == "corr-abc-123"


def test_correlation_id_is_minted_when_absent():
    with TestClient(app) as client:
        response = client.get("/health")
    minted = response.headers.get(CORRELATION_ID_HEADER)
    assert minted and len(minted) >= 16


def test_log_lines_are_valid_json_with_correlation_id():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter("watertwin-api"))
    logger = logging.getLogger("watertwin.test.obs")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    token = set_correlation_id("req-json-42")
    try:
        logger.info("audit chain verified", extra={"events": 3})
    finally:
        reset_correlation_id(token)
        logger.removeHandler(handler)

    obj = json.loads(stream.getvalue().strip())
    assert obj["correlation_id"] == "req-json-42"
    assert obj["service"] == "watertwin-api"
    assert obj["level"] == "INFO"
    assert obj["message"] == "audit chain verified"
    assert obj["events"] == 3


def test_configure_logging_installs_json_formatter_on_root():
    configure_logging("watertwin-api")
    root = logging.getLogger()
    assert any(isinstance(h.formatter, JsonLogFormatter) for h in root.handlers)
