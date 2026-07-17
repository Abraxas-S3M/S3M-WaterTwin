"""Tests for the watertwin-api Simulation Center RO what-if scenario."""

from __future__ import annotations

from app import engine
from simulation_contracts import ROFeed, ROMembrane, ROOperating, SimulateRequest
from watertwin.simulation_center import build_ro_scenario


def _job(job_id: str, req: SimulateRequest):
    result = engine.run_simulate(req)
    return {
        "job_id": job_id,
        "request": req.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
    }


def _baseline_request(**feed_overrides) -> SimulateRequest:
    feed = dict(flow_m3h=100.0, tds_mg_l=35000.0, temperature_c=25.0, pressure_bar=60.0)
    feed.update(feed_overrides)
    return SimulateRequest(
        feed=ROFeed(**feed),
        membrane=ROMembrane(area_m2=1200.0),
        operating=ROOperating(),
    )


def test_scenario_reports_energy_and_quality_deltas():
    baseline = _job("job-baseline", _baseline_request())
    # Scenario: hotter, saltier feed -> higher osmotic pressure.
    scenario = _job("job-scenario", _baseline_request(tds_mg_l=42000.0, temperature_c=30.0))

    card = build_ro_scenario(baseline, scenario, scenario_id="sc-1")

    assert card.scenario_id == "sc-1"
    assert card.deltas.specific_energy_kwh_m3_baseline > 0
    # Higher salinity -> lower recovery than the baseline.
    assert card.deltas.recovery_delta <= 0
    # Deltas are internally consistent.
    d = card.deltas
    assert d.specific_energy_delta_kwh_m3 == (
        d.specific_energy_kwh_m3_scenario - d.specific_energy_kwh_m3_baseline
    )


def test_scenario_confidence_and_provenance():
    baseline = _job("job-b", _baseline_request())
    scenario = _job("job-s", _baseline_request(pressure_bar=65.0))
    card = build_ro_scenario(baseline, scenario)

    assert 0.0 <= card.confidence <= 1.0
    # A well-cross-checked scenario earns reasonable confidence.
    assert card.cross_check_rel_error <= 0.15
    assert card.confidence >= 0.5
    assert card.provenance == "simulated"
    assert card.status == "preliminary"


def test_scenario_feeds_simulation_ids_into_evidence():
    baseline = _job("job-b", _baseline_request())
    scenario = _job("job-s", _baseline_request(pressure_bar=70.0))
    card = build_ro_scenario(baseline, scenario)

    assert card.simulation_ids == ["job-b", "job-s"]
    assert card.evidence is not None
    assert set(card.simulation_ids).issubset(set(card.evidence["simulation_ids"]))
