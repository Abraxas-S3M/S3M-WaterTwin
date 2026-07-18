"""Deny-all egress guard for parser workers, with a tiny explicit allowlist.

The parser workers must not be able to reach the network except for two
destinations: the S3M endpoint and the watertwin-api endpoint. Everything else
is denied by default (data exfiltration prevention). On top of the allowlist,
OT networks / MQTT / OPC UA / Modbus and other industrial protocols are ALWAYS
denied — even if one were mistakenly added to the allowlist — because the ingest
service is read-only to OT and must never touch a control network.

This is the application-layer twin of the Kubernetes NetworkPolicy in
``services/watertwin-ingest/deploy/networkpolicy.yaml``. The two are kept in sync
and both are asserted by the security test-suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import config


class EgressDenied(Exception):
    """Raised when a worker attempts an egress connection that is not allowed."""


class OTNetworkForbidden(EgressDenied):
    """Raised on any attempt to reach an OT / control-network destination.

    This is a distinct, louder failure than a generic allowlist miss: reaching
    OT is not merely "not allowed", it is a safety-invariant violation.
    """


#: Ports that belong to OT / industrial-control / messaging protocols. These are
#: NEVER reachable from the ingest service under any configuration.
OT_FORBIDDEN_PORTS: frozenset[int] = frozenset(
    {
        1883,  # MQTT
        8883,  # MQTT over TLS
        4840,  # OPC UA
        502,  # Modbus/TCP
        20000,  # DNP3
        44818,  # EtherNet/IP
        102,  # IEC 61850 / S7comm (MMS)
        2404,  # IEC 60870-5-104
    }
)

#: Private/OT CIDR prefixes that are always treated as the OT zone and denied.
#: (String-prefix match keeps this dependency-free and explicit.)
OT_FORBIDDEN_HOST_SUFFIXES: tuple[str, ...] = (
    ".ot.local",
    ".scada.local",
    ".plc.local",
)


def _host_port(url_or_host: str, default_port: int = 443) -> tuple[str, int]:
    """Extract ``(host, port)`` from a URL or a bare ``host:port`` string."""
    if "://" in url_or_host:
        parsed = urlparse(url_or_host)
        host = parsed.hostname or ""
        port = parsed.port or (80 if parsed.scheme == "http" else default_port)
        return host, int(port)
    if ":" in url_or_host:
        host, _, port = url_or_host.rpartition(":")
        try:
            return host, int(port)
        except ValueError:
            return url_or_host, default_port
    return url_or_host, default_port


@dataclass
class EgressPolicy:
    """A deny-all-by-default egress allowlist.

    ``allowed`` holds the ``(host, port)`` pairs the workers may reach — by
    default only the S3M and watertwin-api endpoints. OT destinations are always
    denied regardless of ``allowed``.
    """

    allowed: set[tuple[str, int]] = field(default_factory=set)

    @classmethod
    def from_config(cls) -> "EgressPolicy":
        policy = cls()
        for url in (config.S3M_ENDPOINT_URL, config.WATERTWIN_API_URL):
            host, port = _host_port(url)
            if host:
                policy.allow(host, port)
        return policy

    def allow(self, host: str, port: int) -> None:
        """Add ``(host, port)`` to the allowlist (OT destinations are refused)."""
        if self._is_ot(host, port):
            raise OTNetworkForbidden(
                f"refusing to allowlist an OT/control destination: {host}:{port}"
            )
        self.allowed.add((host, int(port)))

    @staticmethod
    def _is_ot(host: str, port: int) -> bool:
        if int(port) in OT_FORBIDDEN_PORTS:
            return True
        host_l = host.lower()
        return any(host_l.endswith(suffix) for suffix in OT_FORBIDDEN_HOST_SUFFIXES)

    def check(self, host: str, port: int) -> None:
        """Raise if ``(host, port)`` may not be reached from a worker."""
        if self._is_ot(host, port):
            raise OTNetworkForbidden(
                f"egress to OT/control network is forbidden: {host}:{port}"
            )
        if (host, int(port)) not in self.allowed:
            raise EgressDenied(
                f"egress to {host}:{port} denied (deny-all; not in allowlist "
                f"{sorted(self.allowed)})"
            )

    def check_url(self, url: str) -> None:
        """Raise if ``url``'s destination may not be reached from a worker."""
        host, port = _host_port(url)
        self.check(host, port)

    def is_allowed(self, host: str, port: int) -> bool:
        try:
            self.check(host, port)
            return True
        except EgressDenied:
            return False
