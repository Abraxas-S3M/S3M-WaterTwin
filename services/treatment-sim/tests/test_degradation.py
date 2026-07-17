"""Membrane-degradation tests."""

from __future__ import annotations

from app import engine
from simulation_contracts import (
    MembraneDegradationRequest,
    ROFeed,
    ROMembrane,
)


def _request(**overrides) -> MembraneDegradationRequest:
    base = dict(
        feed=ROFeed(flow_m3h=100.0, tds_mg_l=35000.0, temperature_c=25.0, pressure_bar=60.0),
        membrane=ROMembrane(area_m2=1200.0),
        a_retention=0.80,
        b_increase=1.5,
    )
    base.update(overrides)
    return MembraneDegradationRequest(**base)


def test_degradation_reduces_normalized_permeate_flow():
    result = engine.run_membrane_degradation(_request())
    assert result.normalized_permeate_flow < 1.0
    assert result.aged.permeate_flow_m3h < result.baseline.permeate_flow_m3h


def test_degradation_increases_salt_passage():
    # Rising B (salt permeability) should raise permeate TDS / lower rejection.
    result = engine.run_membrane_degradation(_request(a_retention=1.0, b_increase=2.0))
    assert result.aged.permeate_tds_mg_l >= result.baseline.permeate_tds_mg_l
    assert result.aged.salt_rejection <= result.baseline.salt_rejection


def test_degradation_labels_preliminary():
    result = engine.run_membrane_degradation(_request())
    assert result.provenance.value == "simulated"
    assert result.status.value == "preliminary"
