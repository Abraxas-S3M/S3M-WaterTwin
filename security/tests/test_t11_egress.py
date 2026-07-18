"""ADR-0014 T11 — Exfiltration / worker egress.

Control: parser workers have deny-all egress with a tiny allowlist (the S3M and
watertwin-api endpoints only). OT networks, MQTT and OPC UA are ALWAYS denied,
even if mistakenly added to the allowlist. The k8s NetworkPolicy is the network-
layer twin and is asserted to agree.
"""

from __future__ import annotations

import os
import re

import pytest
from app.egress import (
    OT_FORBIDDEN_PORTS,
    EgressDenied,
    EgressPolicy,
    OTNetworkForbidden,
)

_NETPOL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "services",
    "watertwin-ingest",
    "deploy",
    "networkpolicy.yaml",
)


def test_default_egress_denies_arbitrary_hosts():
    policy = EgressPolicy.from_config()
    with pytest.raises(EgressDenied):
        policy.check("attacker.example", 443)
    with pytest.raises(EgressDenied):
        policy.check_url("https://exfil.evil/steal")


def test_allowlisted_endpoints_are_reachable():
    policy = EgressPolicy()
    policy.allow("watertwin-api", 8000)
    policy.check("watertwin-api", 8000)  # no raise
    assert policy.is_allowed("watertwin-api", 8000) is True


@pytest.mark.parametrize("port", sorted(OT_FORBIDDEN_PORTS))
def test_ot_ports_always_denied(port):
    policy = EgressPolicy()
    with pytest.raises(OTNetworkForbidden):
        policy.check("some-host", port)


def test_cannot_allowlist_an_ot_destination():
    policy = EgressPolicy()
    with pytest.raises(OTNetworkForbidden):
        policy.allow("plc-1", 502)  # Modbus
    with pytest.raises(OTNetworkForbidden):
        policy.allow("opcua.plant", 4840)  # OPC UA
    with pytest.raises(OTNetworkForbidden):
        policy.allow("broker", 1883)  # MQTT


def test_mqtt_and_opcua_hosts_unreachable():
    policy = EgressPolicy.from_config()
    for host, port in (("mqtt.broker", 1883), ("opcua.plant", 4840), ("historian.ot.local", 443)):
        with pytest.raises((OTNetworkForbidden, EgressDenied)):
            policy.check(host, port)


def test_networkpolicy_manifest_has_no_ot_egress():
    """The k8s NetworkPolicy must not open any OT/MQTT/OPC UA egress port."""
    with open(_NETPOL, encoding="utf-8") as fh:
        text = fh.read()
    assert "kind: NetworkPolicy" in text
    # Deny-all-by-default posture: Egress is a declared policy type.
    assert "Egress" in text
    # No `port: <ot-port>` appears anywhere in the manifest's egress rules.
    declared_ports = {int(p) for p in re.findall(r"port:\s*(\d+)", text)}
    leaked = declared_ports & OT_FORBIDDEN_PORTS
    assert not leaked, f"NetworkPolicy opens forbidden OT port(s): {sorted(leaked)}"
