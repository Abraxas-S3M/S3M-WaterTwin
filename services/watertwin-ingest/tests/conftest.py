"""Shared pytest fixtures for the watertwin-ingest suites."""

from __future__ import annotations

import os

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def fixtures_dir() -> str:
    """Absolute path to the committed test fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def read_fixture():
    """Return a helper that reads a fixture file's raw bytes."""

    def _read(name: str) -> bytes:
        with open(os.path.join(FIXTURES_DIR, name), "rb") as fh:
            return fh.read()

    return _read
