"""Shared fixtures for the watertwin-ingest test suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from ot_ingestion.tag_normalization import TagMap

from app.staging import StagingStore


@pytest.fixture()
def tag_map() -> TagMap:
    """A small, explicit customer tag map (no guessing)."""
    return TagMap.from_dict(
        {
            "map_id": "test-plant",
            "tags": {
                "HIST.PT-101.PV": {
                    "asset_id": "AST-HPP-01",
                    "metric": "discharge_pressure_bar",
                    "unit": "bar",
                },
                "HIST.FT-201.PV": {
                    "asset_id": "AST-RO-01",
                    "metric": "feed_flow_m3h",
                    "unit": "m3/h",
                    "scale": 1.0,
                    "offset": 0.0,
                },
            },
        }
    )


@pytest.fixture()
def staging(tmp_path: Path) -> StagingStore:
    return StagingStore(tmp_path / "staging")
