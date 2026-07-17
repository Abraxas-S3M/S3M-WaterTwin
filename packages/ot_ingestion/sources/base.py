"""Telemetry source abstraction (strictly read-only).

A :class:`TelemetrySource` is the single seam through which the platform
ingests telemetry. Concrete sources are the built-in synthetic plant
(:class:`~app.sources.synthetic.SyntheticSource`) and the read-only OT
connectors (OPC UA / Modbus / historian). Every source only *reads*; no source
exposes any path that writes to a control system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from canonical_water_model import TelemetryReading


class SourceUnavailable(RuntimeError):
    """Raised when a configured source cannot be reached / initialized.

    The source factory catches this and falls back to the synthetic source so
    the service never crashes because a real OT feed is down or misconfigured.
    """


class TelemetrySource(ABC):
    """Read-only telemetry source interface.

    Implementations map their underlying feed onto canonical
    :class:`~canonical_water_model.TelemetryReading` objects.
    """

    #: Machine kind: "synthetic" | "opcua" | "modbus" | "historian".
    kind: str = "abstract"
    #: Human-readable instance name (may embed an endpoint).
    name: str = "abstract"

    @abstractmethod
    def read_latest(self) -> list[TelemetryReading]:
        """Return the latest batch of canonical telemetry readings."""
        raise NotImplementedError

    def probe(self) -> None:
        """Verify the source is reachable / usable.

        Default is a no-op (always available). OT connectors override this to
        attempt a connection and raise :class:`SourceUnavailable` on failure.
        """
        return None

    def describe(self) -> dict:
        """A small, safe description of the source for /health + status."""
        return {"kind": self.kind, "name": self.name}
