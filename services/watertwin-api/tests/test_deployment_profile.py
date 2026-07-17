"""Tests for the DEPLOYMENT_PROFILE fail-closed guard (edge / XiiD one-way diode).

These prove that under ``DEPLOYMENT_PROFILE=one_way_diode`` every platform->OT
request code path is disabled (fail-closed): the platform refuses to initiate a
connection toward the OT zone, both when a telemetry source is resolved and when
the service starts. Under ``standard`` the read-only OT pulls remain available.

The tests are fast and dependency-free: they exercise the deployment guard and
the source resolver with lightweight config stand-ins (no live PLC / historian).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app import deployment, sources
from app.deployment import OneWayDiodeViolation
from app.main import app


def _config(profile: str, ot_source: str = "synthetic", historian_kind: str = "csv"):
    """A minimal config stand-in with just the fields the guard consults."""
    return SimpleNamespace(
        DEPLOYMENT_PROFILE=profile,
        OT_SOURCE=ot_source,
        OT_HISTORIAN_KIND=historian_kind,
        # Enough OT config for the resolver to attempt to build a real source.
        OT_TAG_MAP="example",
        OT_OPCUA_ENDPOINT="opc.tcp://plc:4840",
        OT_OPCUA_NODE_IDS=["ns=2;s=HPP.Temp"],
        OT_MODBUS_HOST="plc",
        OT_MODBUS_PORT=502,
        OT_MODBUS_UNIT=1,
        OT_MODBUS_REGISTERS=["holding:0"],
        OT_HISTORIAN_CSV_PATH="/data/export.csv",
        OT_HISTORIAN_URL="http://historian/api",
        OT_HISTORIAN_DSN="postgresql://reader:reader@historian:5432/h",
        OT_HISTORIAN_QUERY="SELECT tag, value FROM latest",
    )


# --- Profile normalization -------------------------------------------------


def test_known_profiles_are_returned_as_is():
    assert deployment.get_profile(_config("standard")) == deployment.STANDARD
    assert deployment.get_profile(_config("one_way_diode")) == deployment.ONE_WAY_DIODE


def test_unknown_profile_fails_closed_to_one_way_diode():
    # A typo must never accidentally open a platform->OT path.
    assert deployment.get_profile(_config("stanadrd")) == deployment.ONE_WAY_DIODE
    assert deployment.is_one_way_diode(_config("garbage")) is True


def test_unset_profile_defaults_to_standard():
    # Empty / unset is the backward-compatible default (standard), not a typo.
    assert deployment.get_profile(_config("")) == deployment.STANDARD


# --- Direction classification ----------------------------------------------


@pytest.mark.parametrize("kind", ["opcua", "modbus"])
def test_opcua_and_modbus_are_platform_initiated(kind):
    assert deployment.is_platform_initiated_ot(kind, _config("standard")) is True


def test_historian_rest_and_sql_are_platform_initiated():
    assert deployment.is_platform_initiated_ot("historian", _config("standard", historian_kind="rest"))
    assert deployment.is_platform_initiated_ot("historian", _config("standard", historian_kind="sql"))


def test_historian_csv_and_synthetic_are_not_platform_initiated():
    # A CSV drop is a gateway-push / file feed, not a platform->OT connection.
    csv_cfg = _config("standard", historian_kind="csv")
    assert deployment.is_platform_initiated_ot("historian", csv_cfg) is False
    assert deployment.is_platform_initiated_ot("synthetic", _config("standard")) is False


# --- Fail-closed source guard ----------------------------------------------


def test_standard_profile_allows_platform_initiated_ot():
    # No exception: the read-only pull is permitted under the standard profile.
    deployment.assert_source_allowed("opcua", _config("standard"))
    deployment.assert_source_allowed("modbus", _config("standard"))
    deployment.assert_source_allowed("historian", _config("standard", historian_kind="rest"))


@pytest.mark.parametrize(
    "ot_source,historian_kind",
    [("opcua", "csv"), ("modbus", "csv"), ("historian", "rest"), ("historian", "sql")],
)
def test_one_way_diode_blocks_platform_initiated_ot(ot_source, historian_kind):
    with pytest.raises(OneWayDiodeViolation):
        deployment.assert_source_allowed(ot_source, _config("one_way_diode", historian_kind=historian_kind))


def test_one_way_diode_allows_synthetic_and_file_feeds():
    # Synthetic and a gateway-pushed CSV file feed require no platform->OT call.
    deployment.assert_source_allowed("synthetic", _config("one_way_diode"))
    deployment.assert_source_allowed("historian", _config("one_way_diode", historian_kind="csv"))


def test_guard_outbound_ot_is_noop_under_standard_and_raises_under_diode():
    deployment.guard_outbound_ot("opcua.probe", _config("standard"))  # no-op
    with pytest.raises(OneWayDiodeViolation):
        deployment.guard_outbound_ot("opcua.probe", _config("one_way_diode"))


# --- Resolver refuses to build a platform->OT source under diode ------------


def test_resolve_source_refuses_platform_initiated_ot_under_diode():
    # Fail-closed: it raises rather than silently downgrading to synthetic.
    with pytest.raises(OneWayDiodeViolation):
        sources.resolve_source(_config("one_way_diode", ot_source="opcua"), probe=False)


def test_resolve_source_allows_synthetic_under_diode():
    resolution = sources.resolve_source(_config("one_way_diode", ot_source="synthetic"), probe=False)
    assert resolution.active == "synthetic"


# --- Startup enforcement ----------------------------------------------------


def test_enforce_startup_returns_profile_for_safe_config():
    standard = deployment.enforce_startup(_config("standard", ot_source="opcua"))
    assert standard == deployment.STANDARD
    diode = deployment.enforce_startup(_config("one_way_diode", ot_source="synthetic"))
    assert diode == deployment.ONE_WAY_DIODE


def test_enforce_startup_fails_closed_for_platform_initiated_ot_under_diode():
    with pytest.raises(OneWayDiodeViolation):
        deployment.enforce_startup(_config("one_way_diode", ot_source="opcua"))


def test_app_startup_fails_closed_under_diode(monkeypatch):
    """The service must refuse to start if configured to break the one-way rule."""
    monkeypatch.setattr(app_config, "DEPLOYMENT_PROFILE", "one_way_diode", raising=False)
    monkeypatch.setattr(app_config, "OT_SOURCE", "modbus", raising=False)
    with pytest.raises(OneWayDiodeViolation):
        with TestClient(app):
            pass


def test_app_startup_succeeds_under_diode_with_synthetic(monkeypatch):
    monkeypatch.setattr(app_config, "DEPLOYMENT_PROFILE", "one_way_diode", raising=False)
    monkeypatch.setattr(app_config, "OT_SOURCE", "synthetic", raising=False)
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["deployment_profile"] == "one_way_diode"
    assert body["platform_to_ot_enabled"] is False
