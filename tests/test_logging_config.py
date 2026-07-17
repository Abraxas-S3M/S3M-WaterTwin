"""Tests for structured JSON logging."""

from __future__ import annotations

import json
import logging

from watertwin.logging_config import JsonFormatter, configure_logging, get_logger


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="s3m-watertwin.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_valid_json_with_core_fields() -> None:
    payload = json.loads(JsonFormatter().format(_record()))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["service"] == "s3m-watertwin"
    assert payload["control_mode"] == "advisory"
    assert "timestamp" in payload


def test_formatter_merges_structured_context() -> None:
    payload = json.loads(JsonFormatter().format(_record(train_id="train-1")))
    assert payload["train_id"] == "train-1"


def test_configure_logging_is_idempotent() -> None:
    configure_logging()
    configure_logging()
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_get_logger_namespaces_name() -> None:
    assert get_logger("api").name == "s3m-watertwin.api"
