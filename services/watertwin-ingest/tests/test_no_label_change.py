"""CRITICAL invariant: importing historian data changes no analytic label.

Importing customer historian data must NOT promote any analytic from
``preliminary`` to ``calibrated`` (or to ``measured``). Only the documented
validation process, with a named engineer's sign-off, does that. These tests
assert the invariant explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path

from canonical_water_model import DataProvenance, HealthBand, HealthScore
from ot_ingestion.tag_normalization import TagMap

from app.parsers.historian import parse_historian
from app.staging import StagingStore


def _write_csv(path: Path) -> None:
    path.write_text(
        "tag,timestamp,value,quality\n"
        "HIST.PT-101.PV,2026-01-01T00:00:00+00:00,61.2,good\n"
        "HIST.FT-201.PV,2026-01-01T00:05:00+00:00,420.0,good\n",
        encoding="utf-8",
    )


def test_import_leaves_every_analytic_label_unchanged(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    # A representative set of analytics, each carrying a preliminary label.
    analytics = [
        HealthScore(
            asset_id="AST-HPP-01",
            score=72.0,
            band=HealthBand.Monitor,
            provenance=DataProvenance.preliminary,
        ),
        HealthScore(
            asset_id="AST-RO-01",
            score=55.0,
            band=HealthBand.Degraded,
            provenance=DataProvenance.preliminary,
        ),
    ]
    before = [a.model_dump() for a in analytics]

    csv_path = tmp_path / "export.csv"
    _write_csv(csv_path)
    result = parse_historian(csv_path, tag_map=tag_map, staging=staging)

    # The analytics are byte-for-byte unchanged after the import.
    after = [a.model_dump() for a in analytics]
    assert after == before
    assert all(a["provenance"] == DataProvenance.preliminary.value for a in after)

    # The parser itself asserts the invariant.
    assert result.analytic_labels_changed is False
    assert result.promotes_to_calibrated is False
    assert result.proposal.promotes_to_calibrated is False
    assert result.proposal.summary["analytic_labels_changed"] is False


def test_nothing_staged_or_proposed_is_labelled_calibrated_or_measured(
    tmp_path: Path, tag_map: TagMap, staging: StagingStore
) -> None:
    csv_path = tmp_path / "export.csv"
    _write_csv(csv_path)
    result = parse_historian(csv_path, tag_map=tag_map, staging=staging)

    # Staged rows are customer_measured -- never the canonical measured/calibrated.
    staged_text = Path(result.staged.path).read_text()
    for line in staged_text.splitlines():
        if not line:
            continue
        record = json.loads(line)
        assert record["provenance"] == "customer_measured"
        assert record["provenance"] != DataProvenance.measured.value

    blob = json.dumps(result.proposal.to_dict())
    assert "calibrated" not in blob.replace("promotes_to_calibrated", "")
    assert result.staged.provenance == "customer_measured"
