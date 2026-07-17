"""Tests for the three D1 analytics models + their read-only endpoints.

Fast and dependency-free (no live hydraulic-sim). They lock the decision-relevant
invariants for each model: a full ModelSpec is exposed with preliminary
pending-calibration thresholds and documented reused components; assessments are
explainable, advisory and read-only; the synthetic back-tests produce sane
metrics (a false-alarm rate and detection lead time); the benchmark scaffold
aggregates them; and every endpoint carries the control boundary + provenance.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import models
from app.main import app

MODEL_IDS = ["d1-hp-pump-condition", "d1-membrane-fouling", "d1-cartridge-filter"]


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/api/v1/reset")
        yield c


# --- Registry + specs -------------------------------------------------------


def test_registry_has_three_models() -> None:
    assert set(models.list_model_ids()) == set(MODEL_IDS)


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_spec_is_preliminary_and_documents_reuse(model_id: str) -> None:
    spec = models.get_adapter(model_id).spec
    assert spec.tier.value == "D1"
    assert spec.provenance.value == "preliminary"
    assert spec.control_boundary.control_write_enabled is False
    assert spec.inputs and spec.outputs
    # Reused components are documented (nothing duplicated).
    assert spec.reused_components
    # Every threshold is preliminary pending customer calibration.
    assert spec.thresholds
    for th in spec.thresholds:
        assert th.preliminary is True
        assert th.pending_customer_calibration is True


# --- Assessments ------------------------------------------------------------


def test_pump_assessment_is_explainable_and_readonly() -> None:
    ad = models.get_adapter("d1-hp-pump-condition")
    healthy = ad.assess()
    assert healthy.indices["pump_health_index"] == 100.0
    assert 0.0 <= healthy.probabilities["cavitation_probability"] <= 1.0
    assert healthy.control_boundary.control_write_enabled is False

    degraded = ad.assess(
        {
            "vibration_mm_s": 7.5,
            "bearing_temp_c": 96.0,
            "npsh_available_m": 3.1,
            "npsh_required_m": 3.0,
            "pump_curve_efficiency_deviation_pct": 9.0,
        }
    )
    assert degraded.indices["pump_health_index"] < healthy.indices["pump_health_index"]
    assert degraded.contributions  # visible penalties explain the score
    # Low NPSH margin raises cavitation probability and trips the critical rule.
    assert degraded.probabilities["cavitation_probability"] > healthy.probabilities[
        "cavitation_probability"
    ]
    names = {a.name for a in degraded.triggered_alerts}
    assert "NPSH margin low (cavitation)" in names


def test_membrane_assessment_reuses_wq_layer() -> None:
    ad = models.get_adapter("d1-membrane-fouling")
    clean = ad.assess({"fouling": 0.0})
    fouled = ad.assess({"fouling": 0.85})
    assert fouled.indices["membrane_health_index"] < clean.indices["membrane_health_index"]
    assert (
        fouled.probabilities["salt_passage_breakthrough_probability"]
        > clean.probabilities["salt_passage_breakthrough_probability"]
    )
    assert fouled.probabilities["cleaning_required"] == 1.0


def test_cartridge_assessment_flags_plugging() -> None:
    ad = models.get_adapter("d1-cartridge-filter")
    clean = ad.assess({"dp_bar": 0.3, "clean_dp_bar": 0.3, "sdi": 3.0})
    plugged = ad.assess(
        {"dp_bar": 0.9, "clean_dp_bar": 0.3, "sdi": 5.5, "turbidity_ntu": 0.6,
         "particle_count_per_ml": 3000.0}
    )
    assert plugged.indices["filter_health_index"] < clean.indices["filter_health_index"]
    assert (
        plugged.probabilities["replacement_due_probability"]
        > clean.probabilities["replacement_due_probability"]
    )
    assert plugged.indices["remaining_runtime_days"] <= clean.indices["remaining_runtime_days"]


# --- Back-test + benchmark --------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_backtest_metrics_are_wellformed(model_id: str) -> None:
    metrics = models.get_adapter(model_id).backtest()
    assert metrics.samples > 0
    assert metrics.positives + metrics.negatives == metrics.samples
    for rate in (metrics.precision, metrics.recall, metrics.f1, metrics.accuracy,
                 metrics.false_alarm_rate):
        assert 0.0 <= rate <= 1.0
    # The synthetic sets are separable enough that healthy points are not flagged.
    assert metrics.false_alarm_rate == 0.0
    assert metrics.pending_customer_calibration is True


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_benchmark_scaffold_aggregates(model_id: str) -> None:
    result = models.get_adapter(model_id).benchmark()
    assert result.model_id == model_id
    assert 0.0 <= result.brier_score <= 1.0
    assert result.thresholds_preliminary is True
    assert result.drift is not None
    assert "preliminary" in result.disclaimer.lower()


# --- Endpoints --------------------------------------------------------------


def test_list_models_endpoint(client) -> None:
    body = client.get("/api/v1/models").json()
    assert body["control_boundary"]["control_write_enabled"] is False
    ids = {m["model_id"] for m in body["models"]}
    assert ids == set(MODEL_IDS)


_ENDPOINTS = [
    f"/api/v1/models/{mid}/{suffix}"
    for mid in MODEL_IDS
    for suffix in ("spec", "assessment", "backtest", "benchmark")
]


@pytest.mark.parametrize("path", _ENDPOINTS)
def test_model_endpoints_carry_boundary_and_provenance(client, path) -> None:
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["control_boundary"]["control_write_enabled"] is False
    assert body["control_boundary"]["operator_approval_required"] is True
    assert body["provenance"] == "preliminary"


def test_assessment_post_accepts_inputs(client) -> None:
    resp = client.post(
        "/api/v1/models/d1-hp-pump-condition/assessment",
        json={"inputs": {"vibration_mm_s": 7.5, "npsh_available_m": 3.1, "npsh_required_m": 3.0}},
    )
    assert resp.status_code == 200, resp.text
    assessment = resp.json()["assessment"]
    assert assessment["indices"]["pump_health_index"] < 100.0


def test_membrane_assessment_honours_fouling_query(client) -> None:
    clean = client.get("/api/v1/models/d1-membrane-fouling/assessment?fouling=0.0").json()
    fouled = client.get("/api/v1/models/d1-membrane-fouling/assessment?fouling=0.85").json()
    assert (
        fouled["assessment"]["indices"]["membrane_health_index"]
        < clean["assessment"]["indices"]["membrane_health_index"]
    )


def test_unknown_model_returns_404(client) -> None:
    assert client.get("/api/v1/models/d1-nope/spec").status_code == 404
