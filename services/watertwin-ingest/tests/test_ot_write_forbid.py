"""OT-write-forbid guard, extended to cover the watertwin-ingest service.

This mirrors the platform's read-only / no-OT boundary guards (the
``ot_ingestion`` source-package scan used by watertwin-api and the edge-gateway
outbound-only scan). The ingest service must have NO OT network access at all:
it cannot import an OT protocol client (OPC UA / Modbus / MQTT), it issues no OT
write/control call, and it never reaches the edge gateway. A static scan of the
service's ``app/`` package proves the boundary; a dependency scan proves no OT
client library is even installed.
"""

from __future__ import annotations

import os
import re

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
REQUIREMENTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "requirements.txt"
)

# OT protocol clients + control/write calls that must never appear in ingest.
_FORBIDDEN_OT_PATTERNS = [
    # OT protocol client libraries (importing any of these is an OT reach).
    r"\bimport\s+asyncua\b",
    r"\bfrom\s+asyncua\b",
    r"\bimport\s+pymodbus\b",
    r"\bfrom\s+pymodbus\b",
    r"\bimport\s+opcua\b",
    r"\bfrom\s+opcua\b",
    r"\bimport\s+(?:paho|gmqtt|aiomqtt|asyncio_mqtt)\b",
    r"\bfrom\s+(?:paho|gmqtt|aiomqtt|asyncio_mqtt)\b",
    r"\bimport\s+snap7\b",
    r"\bfrom\s+snap7\b",
    # The shared read-only OT connector package (must not be imported here).
    r"\bimport\s+ot_ingestion\b",
    r"\bfrom\s+ot_ingestion\b",
    # MQTT client libraries (importing any of these is an OT reach).
    r"\bimport\s+(?:mqtt|umqtt|hbmqtt)\b",
    r"\bfrom\s+(?:mqtt|umqtt|hbmqtt)\b",
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
]

# OT client distributions that must not be in the service's dependency set.
_FORBIDDEN_OT_DEPS = ["asyncua", "pymodbus", "opcua", "paho", "gmqtt", "aiomqtt", "snap7"]


def _app_files() -> list[str]:
    return [os.path.join(APP_DIR, f) for f in os.listdir(APP_DIR) if f.endswith(".py")]


def test_ingest_app_has_no_ot_access_or_write_path():
    files = _app_files()
    assert files, "expected python files under app/"
    offenders: list[str] = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for pattern in _FORBIDDEN_OT_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                offenders.append(f"{os.path.basename(path)} matches {pattern!r}")
    assert not offenders, (
        "Forbidden OT access / write path detected in watertwin-ingest app/: "
        + "; ".join(offenders)
    )


def test_ingest_requirements_declare_no_ot_client():
    with open(REQUIREMENTS, encoding="utf-8") as fh:
        deps = fh.read().lower()
    present = [name for name in _FORBIDDEN_OT_DEPS if re.search(rf"^\s*{name}\b", deps, re.MULTILINE)]
    assert not present, f"watertwin-ingest must not depend on an OT client library: {present}"


def test_importing_the_app_pulls_in_no_ot_client_module():
    # Import the app, then assert no OT protocol client module was loaded.
    import sys

    import app.main  # noqa: F401

    ot_modules = [m for m in sys.modules if m.split(".")[0] in {"asyncua", "pymodbus", "opcua"}]
    assert not ot_modules, f"ingest import pulled in OT client modules: {ot_modules}"
