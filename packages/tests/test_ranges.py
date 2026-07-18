"""Tests for the engineering specification plausibility ranges.

These ranges back the templated spreadsheet importer's validation: a value that
is out of range must be reported with the specific bound it violated so the
message can be surfaced verbatim in the review diff.
"""

from __future__ import annotations

import pytest

from watertwin_engineering import (
    SPECIFICATION_RANGES,
    SpecRange,
    specification_range,
    specification_range_keys,
)


def test_registry_exposes_the_expected_domains() -> None:
    keys = specification_range_keys()
    assert "equipment.rated_head_m" in keys
    assert "equipment.efficiency_fraction" in keys
    assert "equipment.npshr_m" in keys
    assert "tag_mapping.scale" in keys
    assert "lab.lod" in keys
    assert set(keys) == set(SPECIFICATION_RANGES)


def test_head_of_ten_thousand_metres_is_out_of_range_with_specific_message() -> None:
    rng = specification_range("equipment.rated_head_m")
    msg = rng.error_for(10_000.0)
    assert msg is not None
    assert "0 < value <= 1000 (m)" in msg


def test_efficiency_above_one_is_rejected() -> None:
    rng = specification_range("equipment.efficiency_fraction")
    assert rng.error_for(1.5) is not None
    assert rng.error_for(0.85) is None


def test_negative_npshr_is_rejected_but_zero_allowed() -> None:
    rng = specification_range("equipment.npshr_m")
    assert rng.error_for(-1.0) is not None
    assert rng.error_for(0.0) is None
    assert rng.error_for(3.5) is None


def test_negative_deadband_rejected() -> None:
    rng = specification_range("tag_mapping.deadband")
    assert rng.error_for(-0.1) is not None
    assert rng.error_for(0.0) is None


def test_non_finite_value_is_rejected() -> None:
    rng = specification_range("lab.lod")
    assert rng.error_for(float("nan")) is not None
    assert rng.error_for(float("inf")) is not None


def test_describe_forms_are_readable() -> None:
    inclusive = SpecRange(key="x", unit="m", minimum=0.0, maximum=100.0)
    assert inclusive.describe() == "0 <= value <= 100 (m)"
    exclusive_low = SpecRange(
        key="x", unit="fraction", minimum=0.0, maximum=1.0, inclusive_min=False
    )
    assert exclusive_low.describe() == "0 < value <= 1 (fraction)"
    lower_only = SpecRange(key="x", unit="m", minimum=0.0)
    assert lower_only.describe() == "value >= 0 (m)"


def test_unknown_key_raises() -> None:
    with pytest.raises(KeyError):
        specification_range("does.not.exist")
