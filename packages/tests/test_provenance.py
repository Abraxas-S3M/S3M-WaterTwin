"""Tests for the :class:`DataProvenance` vocabulary and its helpers.

Locks the canonical provenance vocabulary so it can express where a value came
from when it originates from a customer file (vendor datasheet, customer
document, or customer historian/LIMS export) without ever being confused with
live ``measured`` telemetry. Also guards that this PR is behaviour-neutral: no
existing model's DEFAULT provenance is allowed to change.
"""

from __future__ import annotations

import inspect
from itertools import pairwise

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

import canonical_water_model as cwm
from canonical_water_model import (
    PROVENANCE_RANK,
    DataProvenance,
    is_customer_sourced,
)

#: The full 8-member vocabulary, in declaration order.
ALL_MEMBERS = [
    "synthetic",
    "simulated",
    "preliminary",
    "estimated",
    "vendor_specified",
    "customer_supplied",
    "customer_measured",
    "measured",
]

#: The three members added for customer file-ingestion.
CUSTOMER_MEMBERS = {
    DataProvenance.vendor_specified,
    DataProvenance.customer_supplied,
    DataProvenance.customer_measured,
}

#: Expected trust ordering (lowest to highest confidence in reflecting plant
#: reality), for UI display purposes only.
EXPECTED_RANK_ORDER = [
    DataProvenance.synthetic,
    DataProvenance.simulated,
    DataProvenance.preliminary,
    DataProvenance.estimated,
    DataProvenance.customer_supplied,
    DataProvenance.vendor_specified,
    DataProvenance.customer_measured,
    DataProvenance.measured,
]

#: The DEFAULT provenance every canonical model that declares one must keep.
#: This PR must be behaviour-neutral: any change here is a regression.
EXPECTED_MODEL_DEFAULTS = {
    "TelemetryReading": DataProvenance.synthetic,
    "HealthScore": DataProvenance.preliminary,
    "AnomalyResult": DataProvenance.preliminary,
    "WaterQualitySample": DataProvenance.synthetic,
    "ContaminantMatrixRow": DataProvenance.synthetic,
    "ScalingRisk": DataProvenance.preliminary,
    "WaterQualityForecast": DataProvenance.preliminary,
    "WQAlert": DataProvenance.preliminary,
    "ComponentHealth": DataProvenance.preliminary,
    "OperatingEnvelope": DataProvenance.preliminary,
    "RemainingUsefulLife": DataProvenance.preliminary,
    "FailureProbability": DataProvenance.preliminary,
    "MaintenancePriority": DataProvenance.preliminary,
    "RootCauseRanking": DataProvenance.preliminary,
    "MembraneHealth": DataProvenance.preliminary,
    "PdMRecommendation": DataProvenance.preliminary,
    "MaintenanceWorkOrder": DataProvenance.preliminary,
    "AssetMaintenanceRecord": DataProvenance.synthetic,
    "EnergyOptimizationResult": DataProvenance.estimated,
    "EnergyLoss": DataProvenance.estimated,
    "ResilienceCriticality": DataProvenance.preliminary,
    "GeneratorStatus": DataProvenance.preliminary,
    "LoadShedPlan": DataProvenance.preliminary,
    "ServiceContinuity": DataProvenance.preliminary,
    "ValueComponent": DataProvenance.estimated,
    "ExecutiveValueSummary": DataProvenance.estimated,
    "ROIEstimate": DataProvenance.estimated,
    "AssistantResponse": DataProvenance.preliminary,
    "ComplianceEvaluation": DataProvenance.synthetic,
    "ModelRegistryEntry": DataProvenance.preliminary,
}


def _actual_model_defaults() -> dict[str, DataProvenance]:
    """Collect the default of every canonical model with a ``DataProvenance``
    ``provenance`` field, discovered by reflection over the package namespace."""
    found: dict[str, DataProvenance] = {}
    for name, obj in inspect.getmembers(cwm):
        if not (inspect.isclass(obj) and issubclass(obj, BaseModel)):
            continue
        field = obj.model_fields.get("provenance")
        if field is None:
            continue
        default = field.default
        if isinstance(default, DataProvenance):
            found[name] = default
    return found


def test_all_eight_members_present_with_matching_string_values():
    assert [m.name for m in DataProvenance] == ALL_MEMBERS
    for member in DataProvenance:
        # ``str`` enum whose value equals its member name.
        assert member.value == member.name
        assert isinstance(member, str)


def test_is_customer_sourced_true_for_exactly_the_three_new_members():
    for member in DataProvenance:
        expected = member in CUSTOMER_MEMBERS
        assert is_customer_sourced(member) is expected
    assert {m for m in DataProvenance if is_customer_sourced(m)} == CUSTOMER_MEMBERS
    # ``measured`` (live telemetry) is explicitly NOT customer-sourced.
    assert is_customer_sourced(DataProvenance.measured) is False


def test_provenance_rank_covers_every_member_once_and_is_strictly_ordered():
    # Every member is ranked exactly once.
    assert set(PROVENANCE_RANK) == set(DataProvenance)
    assert len(PROVENANCE_RANK) == len(list(DataProvenance))
    # Ranks are the contiguous integers 0..7 (each used exactly once).
    assert sorted(PROVENANCE_RANK.values()) == list(range(len(DataProvenance)))
    # Strictly increasing along the documented trust ordering.
    ordered = sorted(PROVENANCE_RANK, key=lambda m: PROVENANCE_RANK[m])
    assert ordered == EXPECTED_RANK_ORDER
    ranks = [PROVENANCE_RANK[m] for m in EXPECTED_RANK_ORDER]
    assert all(a < b for a, b in pairwise(ranks))
    # Customer-measured is trusted below live measured telemetry.
    assert (
        PROVENANCE_RANK[DataProvenance.customer_measured]
        < PROVENANCE_RANK[DataProvenance.measured]
    )


def test_no_existing_model_default_provenance_changed():
    actual = _actual_model_defaults()
    # Exactly the known set of models declare a DataProvenance default...
    assert set(actual) == set(EXPECTED_MODEL_DEFAULTS)
    # ...and each keeps its original default (behaviour-neutral change).
    assert actual == EXPECTED_MODEL_DEFAULTS


def test_no_model_defaults_to_a_customer_sourced_provenance():
    # No canonical model may silently default to a customer-file provenance.
    for name, default in _actual_model_defaults().items():
        assert not is_customer_sourced(default), name


def test_measured_default_is_never_undefined_sentinel():
    # Guard the reflection helper: fields we skip are genuinely non-DataProvenance.
    field = cwm.TelemetryReading.model_fields["provenance"]
    assert field.default is not PydanticUndefined
