"""Tests locking template<->parser consistency (templates cannot drift)."""

from __future__ import annotations

import os

import pytest

from app.parsers import (
    PARSERS,
    TEMPLATE_FILENAMES,
    TEMPLATES_DIR,
    render_all_templates,
)


def test_all_three_templates_are_defined() -> None:
    assert set(TEMPLATE_FILENAMES) == {"equipment", "tag_mapping", "lab"}
    assert len(render_all_templates()) == 3


@pytest.mark.parametrize("filename", sorted(TEMPLATE_FILENAMES.values()))
def test_committed_template_matches_the_contract(filename: str) -> None:
    """The committed CSV must equal what the contract renders (no drift)."""
    path = os.path.join(TEMPLATES_DIR, filename)
    assert os.path.exists(path), f"missing committed template {filename}"
    with open(path, encoding="utf-8", newline="") as fh:
        committed = fh.read()
    rendered = render_all_templates()[filename]
    assert committed == rendered, (
        f"{filename} is out of date; regenerate with "
        "`python -c 'from app.parsers import write_templates; write_templates()'`"
    )


@pytest.mark.parametrize("kind", sorted(PARSERS))
def test_each_template_round_trips_through_its_own_parser(kind: str) -> None:
    parser = PARSERS[kind]
    report = parser.parse(parser.template_csv().encode("utf-8"), f"{kind}.csv")
    assert report.ok
    assert report.warnings == []
    assert len(report.records) == 1
    assert report.records[0]["provenance"] == parser.PROVENANCE
