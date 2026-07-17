"""Tests for the read-only OT telemetry sources + the read-only boundary guard.

These are fast and dependency-free: the OPC UA / Modbus connectors are exercised
with injected fake clients (no live PLC / server), the historian via a CSV
export, the graceful fallback via an unreachable real source, and the read-only
invariant via a source-package scan for forbidden write calls.
"""

from __future__ import annotations

import os
import re
import types

import pytest
from fastapi.testclient import TestClient

from app import sources, tag_normalization as tn
from app.main import app
from app.sources.modbus import ModbusSource, parse_register_specs
from app.sources.opcua import OpcUaSource
from app.sources.historian import HistorianSource
from app.sources.synthetic import SyntheticSource

# The OT source adapters were moved to the shared, importable
# ``ot_ingestion.sources`` package (reused by both this API and the
# edge-gateway). The read-only boundary guard scans that MOVED package, not the
# thin ``app.sources`` compatibility shim, so the invariant is enforced wherever
# the real adapter logic lives.
from ot_ingestion import sources as shared_sources

SOURCES_DIR = os.path.dirname(os.path.abspath(shared_sources.__file__))


# --- Synthetic source -------------------------------------------------------


def test_synthetic_source_yields_readings():
    readings = SyntheticSource().read_latest()
    assert readings, "synthetic source should yield readings"
    assert all(r.provenance.value == "synthetic" for r in readings)
    # Wraps the existing synthetic plant telemetry (predictive_maintenance ASSETS).
    hpp = [r for r in readings if r.asset_id == "AST-HPP-01"]
    metrics = {r.metric for r in hpp}
    assert "winding_temp_c" in metrics
    assert next(r for r in hpp if r.metric == "winding_temp_c").unit == "degC"


# --- Modbus source (read function codes only) -------------------------------


class _ModbusResp:
    def __init__(self, registers=None, bits=None):
        self.registers = registers or []
        self.bits = bits or []

    def isError(self):
        return False


class FakeModbusClient:
    """Records every method invoked so the test can assert read-only usage."""

    def __init__(self, values):
        self._values = values
        self.calls: list[str] = []

    def connect(self):
        self.calls.append("connect")
        return True

    def close(self):
        self.calls.append("close")

    def read_holding_registers(self, address, count=1, slave=1):
        self.calls.append("read_holding_registers")
        return _ModbusResp(registers=[self._values[("holding", address)]])

    def read_input_registers(self, address, count=1, slave=1):
        self.calls.append("read_input_registers")
        return _ModbusResp(registers=[self._values[("input", address)]])

    def read_coils(self, address, count=1, slave=1):
        self.calls.append("read_coils")
        return _ModbusResp(bits=[self._values[("coil", address)]])

    def read_discrete_inputs(self, address, count=1, slave=1):
        self.calls.append("read_discrete_inputs")
        return _ModbusResp(bits=[self._values[("discrete", address)]])


def test_modbus_source_reads_and_maps_with_read_codes_only():
    fake = FakeModbusClient({("holding", 0): 1500, ("holding", 1): 640, ("input", 0): 570})
    tag_map = tn.load_tag_map("modbus-example")
    source = ModbusSource(
        host="127.0.0.1",
        port=502,
        unit=1,
        registers=parse_register_specs(["holding:0", "holding:1", "input:0"]),
        tag_map=tag_map,
        client=fake,
    )
    readings = {(r.asset_id, r.metric): r for r in source.read_latest()}

    assert readings[("AST-HPP-01", "winding_temp_c")].value == pytest.approx(150.0)  # 1500 * 0.1
    assert readings[("AST-HPP-01", "vibration_mm_s")].value == pytest.approx(6.4)  # 640 * 0.01
    assert readings[("AST-CF-01", "dp_bar")].value == pytest.approx(0.57)  # 570 * 0.001

    # Only read function codes (+ connect/close) were ever invoked.
    used = set(fake.calls)
    assert used <= {"connect", "close", "read_holding_registers", "read_input_registers",
                    "read_coils", "read_discrete_inputs"}
    assert not any(c.startswith("write") for c in fake.calls)


# --- OPC UA source (client read only) ---------------------------------------


class _FakeNode:
    def __init__(self, value):
        self._value = value

    async def read_value(self):
        return self._value


class FakeOpcClient:
    def __init__(self, values):
        self._values = values
        self.connected = False
        self.accessed: list[str] = []

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    def get_node(self, node_id):
        self.accessed.append(node_id)
        return _FakeNode(self._values[node_id])


def test_opcua_source_reads_and_maps_client_only():
    fake = FakeOpcClient({"ns=2;s=HPP_A.WindingTemp": 150.0, "ns=2;s=HPP_A.Vibration": 6.4})
    tag_map = tn.load_tag_map("opcua-example")
    source = OpcUaSource(
        endpoint="opc.tcp://127.0.0.1:4840",
        node_ids=["ns=2;s=HPP_A.WindingTemp", "ns=2;s=HPP_A.Vibration"],
        tag_map=tag_map,
        client=fake,
    )
    readings = {(r.asset_id, r.metric): r for r in source.read_latest()}
    assert readings[("AST-HPP-01", "winding_temp_c")].value == pytest.approx(150.0)
    assert readings[("AST-HPP-01", "vibration_mm_s")].value == pytest.approx(6.4)
    assert fake.connected is False  # disconnected after read


# --- Historian source (read-only CSV pull) ----------------------------------


def test_historian_csv_source_reads_and_maps(tmp_path):
    csv_path = tmp_path / "export.csv"
    csv_path.write_text(
        "tag,value\nPLC1.HPP_A.WINDING_TEMP,150.0\nPLC1.HPP_A.VIBRATION,6.4\n",
        encoding="utf-8",
    )
    tag_map = tn.load_tag_map("example-plant")
    source = HistorianSource(tag_map=tag_map, access="csv", csv_path=str(csv_path))
    readings = {(r.asset_id, r.metric): r for r in source.read_latest()}
    assert readings[("AST-HPP-01", "winding_temp_c")].value == pytest.approx(150.0)
    assert readings[("AST-HPP-01", "vibration_mm_s")].value == pytest.approx(6.4)


def test_historian_sql_rejects_non_select():
    tag_map = tn.load_tag_map("example-plant")
    with pytest.raises(ValueError):
        HistorianSource(tag_map=tag_map, access="sql", dsn="x", query="DROP TABLE readings")


# --- Graceful fallback ------------------------------------------------------


def _unreachable_historian_config() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        OT_SOURCE="historian",
        OT_TAG_MAP="example-plant",
        OT_HISTORIAN_KIND="csv",
        OT_HISTORIAN_CSV_PATH="/nonexistent/path/historian-export.csv",
        OT_HISTORIAN_URL=None,
        OT_HISTORIAN_DSN=None,
        OT_HISTORIAN_QUERY=None,
    )


def test_configured_but_unreachable_source_falls_back_to_synthetic():
    resolution = sources.resolve_source(_unreachable_historian_config())
    assert resolution.requested == "historian"
    assert resolution.active == "synthetic"
    assert resolution.fallback is True
    assert resolution.reason
    # The fallback source still yields readings.
    assert resolution.source.read_latest()


def test_unknown_source_falls_back_to_synthetic():
    cfg = types.SimpleNamespace(OT_SOURCE="does-not-exist", OT_TAG_MAP=None)
    resolution = sources.resolve_source(cfg)
    assert resolution.active == "synthetic"
    assert resolution.fallback is True


def test_health_reports_active_source_and_fallback():
    resolution = sources.resolve_source(_unreachable_historian_config())
    with TestClient(app) as c:
        app.state.source_resolution = resolution
        try:
            body = c.get("/health").json()
        finally:
            del app.state.source_resolution
    assert body["telemetry_source"] == "synthetic"
    assert body["telemetry_source_requested"] == "historian"
    assert body["telemetry_source_fallback"] is True
    assert body["telemetry"]["fallback_reason"]


# --- Read-only boundary guard (mirrors the control-write boundary guard) ----

#: Forbidden write-path call patterns. If any appears in app/sources/, a
#: control-write path may have been introduced and this test fails the build.
_FORBIDDEN_PATTERNS = [
    # OPC UA node writes / attribute sets.
    r"\bwrite_value\b",
    r"\bwrite_values\b",
    r"\bset_value\b",
    r"\bset_values\b",
    r"\bwrite_attribute\b",
    r"\bwrite_attributes\b",
    # Modbus write function codes.
    r"\bwrite_coil\b",
    r"\bwrite_coils\b",
    r"\bwrite_register\b",
    r"\bwrite_registers\b",
    r"\bmask_write_register\b",
    # HTTP write verbs (historian REST is GET-only).
    r"\.post\(",
    r"\.put\(",
    r"\.patch\(",
    r"\.delete\(",
    # SQL write statements (historian SQL is SELECT-only).
    r"(?i)\binsert\s+into\b",
    r"(?i)\bupdate\s+\w+\s+set\b",
    r"(?i)\bdelete\s+from\b",
    r"(?i)\bdrop\s+table\b",
    r"(?i)\btruncate\s+table\b",
    r"(?i)\balter\s+table\b",
]


def _source_files() -> list[str]:
    return [
        os.path.join(SOURCES_DIR, f)
        for f in os.listdir(SOURCES_DIR)
        if f.endswith(".py")
    ]


def test_sources_package_has_no_write_path():
    files = _source_files()
    assert files, "expected python files under app/sources/"
    offenders: list[str] = []
    for path in files:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        for pattern in _FORBIDDEN_PATTERNS:
            if re.search(pattern, text):
                offenders.append(f"{os.path.basename(path)} matches {pattern!r}")
    assert not offenders, (
        "Forbidden OT write path detected in app/sources/: "
        + "; ".join(offenders)
    )
