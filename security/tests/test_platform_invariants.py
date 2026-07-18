"""ADR-0014 — Platform-wide safety invariants over the ingest service.

Covers the four cross-cutting invariants the threat model requires:

* the advisory/read-only safety invariant holds across the ingest service;
* the OT-write-forbid guard covers the ingest service (no control-write path);
* the ingest service is optional — the platform is fully functional without it;
* a one-way ``DEPLOYMENT_PROFILE`` disables ingestion and hides the nav item.
"""

from __future__ import annotations

import os
import re

import pytest
from app.control_boundary import CONTROL_BOUNDARY, safety_invariant_intact
from app.deployment import IngestionDisabled
from app.service import IngestService

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INGEST_APP = os.path.join(REPO_ROOT, "services", "watertwin-ingest", "app")


# --- Safety invariant holds across the service ------------------------------ #


def test_safety_invariant_intact():
    assert safety_invariant_intact() is True
    assert CONTROL_BOUNDARY.control_mode == "advisory"
    assert CONTROL_BOUNDARY.operator_approval_required is True
    assert CONTROL_BOUNDARY.control_write_enabled is False


def test_every_response_stamps_the_read_only_boundary():
    caps = IngestService(profile="standard").capabilities()
    assert caps["control_boundary"]["control_write_enabled"] is False
    assert caps["control_boundary"]["control_mode"] == "advisory"
    assert caps["safety_invariant_intact"] is True


# --- OT-write-forbid guard covers the ingest service ------------------------ #

#: Forbidden control-write / OT-write CODE patterns. These match write-path
#: *constructs* (not the protocol names used defensively in the egress denylist),
#: so a real control-write path is build-breaking while the deny-all egress guard
#: is free to name the protocols it blocks. Case-sensitive on purpose: Python's
#: boolean is ``True`` (capital T); the lowercase ``true`` in the prompt-injection
#: marker string is intentionally NOT a match.
_FORBIDDEN_PATTERNS = [
    r"control_write_enabled\s*=\s*True",
    # OPC UA node writes / attribute sets.
    r"\bwrite_value\b",
    r"\bwrite_values\b",
    r"\bset_value\b",
    r"\bwrite_attribute\b",
    # Modbus write function codes.
    r"\bwrite_coil\b",
    r"\bwrite_coils\b",
    r"\bwrite_register\b",
    r"\bwrite_registers\b",
    r"\bmask_write_register\b",
    # MQTT publish (a control command channel).
    r"\.publish\(",
    # Importing an OT client library (this service must never speak to OT).
    r"import\s+paho",
    r"paho\.mqtt",
    r"import\s+asyncua",
    r"from\s+asyncua",
    r"import\s+pymodbus",
    r"from\s+pymodbus",
    # Connecting to an OPC UA endpoint.
    r"opc\.tcp://",
]


def _ingest_source_files() -> list[str]:
    files: list[str] = []
    for dirpath, _dirs, names in os.walk(INGEST_APP):
        for name in names:
            if name.endswith(".py"):
                files.append(os.path.join(dirpath, name))
    return files


def test_ot_write_forbid_guard_covers_ingest_service():
    files = _ingest_source_files()
    assert files, "expected python files under services/watertwin-ingest/app"
    offenders: list[str] = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for pattern in _FORBIDDEN_PATTERNS:
            if re.search(pattern, text):
                offenders.append(f"{os.path.relpath(path, REPO_ROOT)} matches {pattern!r}")
    assert not offenders, "Forbidden OT/control-write path in ingest service: " + "; ".join(
        offenders
    )


# --- Ingest stopped -> platform fully functional ---------------------------- #


def test_no_other_component_imports_the_ingest_service():
    """Nothing under packages/ or the other services imports watertwin-ingest.

    Because nothing depends on the ingest service, stopping it cannot break the
    platform. (The ingest service uses the shared packages, never the reverse.)
    """
    ingest_root = os.path.join(REPO_ROOT, "services", "watertwin-ingest")
    scanned = 0
    offenders: list[str] = []
    for base in (os.path.join(REPO_ROOT, "packages"), os.path.join(REPO_ROOT, "services")):
        for dirpath, _dirs, names in os.walk(base):
            if os.path.commonpath([os.path.abspath(dirpath), ingest_root]) == ingest_root:
                continue  # skip the ingest service's own tree
            for name in names:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                scanned += 1
                # Only the hyphenated service *path* uniquely identifies a
                # dependency on this deployable (the underscore form appears in
                # unrelated metric names such as ``watertwin_ingest_events``).
                if "watertwin-ingest" in text:
                    offenders.append(os.path.relpath(path, REPO_ROOT))
    assert scanned > 0
    assert not offenders, f"Platform components depend on the ingest service: {offenders}"


def test_capabilities_report_service_is_optional():
    assert IngestService(profile="standard").capabilities()["optional"] is True


# --- One-way DEPLOYMENT_PROFILE -> ingestion disabled, nav item absent ------ #


def test_one_way_diode_disables_ingestion_and_hides_nav():
    svc = IngestService(profile="one_way_diode")
    caps = svc.capabilities()
    assert caps["deployment_profile"] == "one_way_diode"
    assert caps["ingestion_enabled"] is False
    # The dashboard nav item is absent under the one-way profile.
    assert caps["nav"]["ingestion"]["visible"] is False
    # ...and an actual upload attempt fails closed.
    with pytest.raises(IngestionDisabled):
        svc.upload(
            tenant_id="TEN-A",
            uploaded_by="alice",
            filename="lab.csv",
            data=b"analyte,value\n",
            parser="csv",
        )


def test_unknown_profile_fails_closed_to_one_way_diode():
    svc = IngestService(profile="typo-profile")
    assert svc.capabilities()["ingestion_enabled"] is False


def test_standard_profile_enables_ingestion_and_nav():
    caps = IngestService(profile="standard").capabilities()
    assert caps["ingestion_enabled"] is True
    assert caps["nav"]["ingestion"]["visible"] is True
