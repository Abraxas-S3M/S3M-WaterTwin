"""Tests for the deterministic water-quality calculations.

These lock the critical, decision-relevant invariants of the Water Quality
Intelligence physics: LSI sign, boron pH-dependence, sulfate saturation
behaviour, silica screening, and the normalisation indices that separate real
membrane deterioration from operating changes.
"""

from __future__ import annotations

import pytest

from watertwin_engineering import (
    boron_rejection,
    colloidal_fouling_index,
    langelier_saturation_index,
    normalized_differential_pressure,
    normalized_salt_passage,
    silica_saturation_pct,
    sulfate_scaling_ratio,
)


# --- Langelier Saturation Index --------------------------------------------


def test_lsi_positive_for_scaling_prone_water() -> None:
    # Alkaline, hard, well-buffered water -> CaCO3 scaling tendency (LSI > 0).
    lsi = langelier_saturation_index(
        ph=8.2,
        tds_mg_l=500.0,
        calcium_mg_l_as_caco3=300.0,
        alkalinity_mg_l_as_caco3=250.0,
        temperature_c=25.0,
    )
    assert lsi > 0.0


def test_lsi_negative_for_corrosive_water() -> None:
    # Soft, poorly buffered, mildly acidic water -> corrosive (LSI < 0).
    lsi = langelier_saturation_index(
        ph=6.8,
        tds_mg_l=50.0,
        calcium_mg_l_as_caco3=10.0,
        alkalinity_mg_l_as_caco3=15.0,
        temperature_c=15.0,
    )
    assert lsi < 0.0


def test_lsi_rises_with_ph() -> None:
    base = dict(
        tds_mg_l=500.0,
        calcium_mg_l_as_caco3=200.0,
        alkalinity_mg_l_as_caco3=180.0,
        temperature_c=25.0,
    )
    assert langelier_saturation_index(ph=8.5, **base) > langelier_saturation_index(
        ph=7.0, **base
    )


def test_lsi_validates_inputs() -> None:
    with pytest.raises(ValueError):
        langelier_saturation_index(
            ph=15.0,
            tds_mg_l=500.0,
            calcium_mg_l_as_caco3=200.0,
            alkalinity_mg_l_as_caco3=180.0,
            temperature_c=25.0,
        )
    with pytest.raises(ValueError):
        langelier_saturation_index(
            ph=8.0,
            tds_mg_l=0.0,
            calcium_mg_l_as_caco3=200.0,
            alkalinity_mg_l_as_caco3=180.0,
            temperature_c=25.0,
        )


# --- Sulfate scaling ratio --------------------------------------------------


def test_sulfate_ratio_rises_with_cation_and_sulfate() -> None:
    low = sulfate_scaling_ratio(cation_mg_l=400.0, sulfate_mg_l=2000.0, salt="CaSO4")
    high = sulfate_scaling_ratio(cation_mg_l=800.0, sulfate_mg_l=4000.0, salt="CaSO4")
    assert high > low
    # Doubling both concentrations quadruples the ion product (ratio ~4x).
    assert high == pytest.approx(4.0 * low, rel=1e-9)


def test_sulfate_ratio_supersaturation_flag() -> None:
    # Barite is extremely insoluble; modest Ba with high sulfate super-saturates.
    ratio = sulfate_scaling_ratio(cation_mg_l=5.0, sulfate_mg_l=3000.0, salt="BaSO4")
    assert ratio > 1.0


def test_sulfate_ratio_unknown_salt_raises() -> None:
    with pytest.raises(ValueError):
        sulfate_scaling_ratio(cation_mg_l=400.0, sulfate_mg_l=2000.0, salt="NaCl")


# --- Silica saturation ------------------------------------------------------


def test_silica_saturation_scales_with_concentration() -> None:
    low = silica_saturation_pct(silica_mg_l=30.0, temperature_c=25.0, ph=7.5)
    high = silica_saturation_pct(silica_mg_l=120.0, temperature_c=25.0, ph=7.5)
    assert high > low
    assert high == pytest.approx(100.0, rel=1e-6)  # 120 mg/L == 25 C solubility


def test_silica_solubility_rises_with_temperature_and_high_ph() -> None:
    warm = silica_saturation_pct(silica_mg_l=100.0, temperature_c=40.0, ph=7.5)
    cold = silica_saturation_pct(silica_mg_l=100.0, temperature_c=25.0, ph=7.5)
    # Warmer water dissolves more silica -> lower saturation percentage.
    assert warm < cold
    high_ph = silica_saturation_pct(silica_mg_l=100.0, temperature_c=25.0, ph=9.5)
    assert high_ph < cold


# --- Boron rejection --------------------------------------------------------


def test_boron_rejection_increases_with_ph() -> None:
    low = boron_rejection(ph=7.0, temperature_c=25.0)
    mid = boron_rejection(ph=9.2, temperature_c=25.0)
    high = boron_rejection(ph=10.5, temperature_c=25.0)
    assert low < mid < high


def test_boron_rejection_in_unit_interval() -> None:
    for ph in (5.0, 7.0, 9.0, 11.0, 13.0):
        r = boron_rejection(ph=ph, temperature_c=25.0)
        assert 0.0 <= r <= 1.0


def test_boron_rejection_derated_by_membrane_age() -> None:
    fresh = boron_rejection(ph=9.5, temperature_c=25.0, membrane_age_factor=1.0)
    aged = boron_rejection(ph=9.5, temperature_c=25.0, membrane_age_factor=0.8)
    assert aged < fresh


# --- Normalized indices -----------------------------------------------------


def test_normalized_salt_passage_reacts_to_fouling() -> None:
    # A membrane deteriorating at fixed operating point: raw salt passage rises,
    # and so does the normalized value.
    ref = normalized_salt_passage(
        salt_passage=0.010, ndp_bar=20.0, temperature_c=25.0, ref_ndp_bar=20.0
    )
    fouled = normalized_salt_passage(
        salt_passage=0.020, ndp_bar=20.0, temperature_c=25.0, ref_ndp_bar=20.0
    )
    assert fouled > ref


def test_normalized_salt_passage_removes_pressure_effect() -> None:
    # Same membrane, higher NDP lowers raw SP; normalization scales it back so
    # the deterioration signal is comparable across operating points.
    norm = normalized_salt_passage(
        salt_passage=0.008, ndp_bar=25.0, temperature_c=25.0, ref_ndp_bar=20.0
    )
    assert norm == pytest.approx(0.008 * (25.0 / 20.0), rel=1e-9)


def test_normalized_dp_flags_fouling_when_flow_drops() -> None:
    # dP holding up while feed flow falls implies fouling: normalized dP rises.
    clean = normalized_differential_pressure(dp_bar=0.8, flow_m3h=50.0, ref_flow_m3h=50.0)
    fouling = normalized_differential_pressure(dp_bar=0.8, flow_m3h=40.0, ref_flow_m3h=50.0)
    assert fouling > clean


def test_colloidal_fouling_index_bounded_and_monotonic() -> None:
    clean = colloidal_fouling_index(sdi=1.0, turbidity_ntu=0.1, particle_count=100.0)
    dirty = colloidal_fouling_index(sdi=5.5, turbidity_ntu=3.0, particle_count=4000.0)
    assert 0.0 <= clean <= 1.0
    assert 0.0 <= dirty <= 1.0
    assert dirty > clean
