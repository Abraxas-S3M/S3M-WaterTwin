"""Observability tests for treatment-sim.

Assert that ``/metrics`` exposes the expected Prometheus series (HTTP request
latency/throughput plus the job buffer-depth and RO model-drift gauges) and
that log lines are valid JSON carrying a correlation id.
"""

from __future__ import annotations

import io
import json
import logging

from fastapi.testclient import TestClient

from watertwin_observability import (
    CORRELATION_ID_HEADER,
    JsonLogFormatter,
    reset_correlation_id,
    set_correlation_id,
)

from app.main import app

EXPECTED_SERIES = (
    "http_requests_total",
    "http_request_duration_seconds",
    "http_requests_in_progress",
    "watertwin_buffer_depth",
    "watertwin_model_drift_ratio",
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
    assert 'service="treatment-sim"' in body
    assert 'model="ro_baseline"' in body


def test_correlation_id_round_trip():
    with TestClient(app) as client:
        supplied = client.get("/health", headers={CORRELATION_ID_HEADER: "trt-corr-1"})
        minted = client.get("/health")
    assert supplied.headers.get(CORRELATION_ID_HEADER) == "trt-corr-1"
    assert minted.headers.get(CORRELATION_ID_HEADER)
    assert len(minted.headers[CORRELATION_ID_HEADER]) >= 16


def test_log_lines_are_valid_json_with_correlation_id():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter("treatment-sim"))
    logger = logging.getLogger("treatment.test.obs")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    token = set_correlation_id("trt-json-9")
    try:
        logger.info("optimize solved", extra={"engine": "analytical"})
    finally:
        reset_correlation_id(token)
        logger.removeHandler(handler)

    obj = json.loads(stream.getvalue().strip())
    assert obj["correlation_id"] == "trt-json-9"
    assert obj["service"] == "treatment-sim"
    assert obj["message"] == "optimize solved"
    assert obj["engine"] == "analytical"
