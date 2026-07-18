"""ADR-0014 T9 — Poisoned configuration (out-of-range values).

Control: uploaded configuration is validated against the shared canonical
engineering models; physically-impossible / out-of-range values are rejected.
"""

from __future__ import annotations

import pytest
from app.engineering_validation import PoisonedConfig, validate_config_entity


def test_out_of_range_membrane_recovery_rejected():
    # max_recovery must be 0 < r < 1; 2.0 is physically impossible.
    poisoned = {
        "model_name": "evil-membrane",
        "active_area_m2": 37.0,
        "nominal_salt_rejection_pct": 99.7,
        "max_feed_pressure_bar": 82.0,
        "max_feed_flow_m3h": 16.0,
        "min_concentrate_flow_m3h": 3.0,
        "max_recovery": 2.0,
    }
    with pytest.raises(PoisonedConfig):
        validate_config_entity("membrane_model", poisoned)


def test_out_of_range_efficiency_rejected():
    # efficiency_bep must be 0 < e <= 1; 5.0 is out of range.
    with pytest.raises(PoisonedConfig):
        validate_config_entity(
            "rated_equipment", {"asset_id": "PU-1", "efficiency_bep": 5.0}
        )


def test_disordered_alarm_thresholds_rejected():
    with pytest.raises(PoisonedConfig):
        validate_config_entity(
            "alarm_threshold",
            {"asset_id": "PU-1", "metric": "vibration_mm_s", "lo": 9.0, "hi": 1.0},
        )


def test_unknown_entity_type_rejected():
    with pytest.raises(PoisonedConfig):
        validate_config_entity("controller_setpoint", {"value": 1})


def test_valid_config_accepted():
    ok = validate_config_entity(
        "membrane_model",
        {
            "model_name": "SW30HRLE-440",
            "active_area_m2": 41.0,
            "nominal_salt_rejection_pct": 99.7,
            "max_feed_pressure_bar": 83.0,
            "max_feed_flow_m3h": 16.0,
            "min_concentrate_flow_m3h": 3.0,
            "max_recovery": 0.5,
        },
    )
    assert ok["model_name"] == "SW30HRLE-440"
    assert ok["max_recovery"] == 0.5
