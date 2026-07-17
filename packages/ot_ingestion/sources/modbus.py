"""Modbus telemetry source (pymodbus, strictly read-only function codes only).

Reads process values from a Modbus TCP device using ONLY the four read function
codes -- read coils, read discrete inputs, read holding registers, read input
registers -- and maps them onto the canonical model via the tag-normalization
layer. No write function code (write coil / write register / ...) is used or
referenced anywhere; this source can never actuate a device.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from canonical_water_model import TelemetryReading

from ..tag_normalization import RawReading, TagMap, normalize
from .base import SourceUnavailable, TelemetrySource

#: The four read function codes we support. Register "kind" -> reader-method name
#: on a pymodbus client. Deliberately read-only: there is no write mapping.
_READ_METHODS: dict[str, str] = {
    "coil": "read_coils",
    "discrete": "read_discrete_inputs",
    "holding": "read_holding_registers",
    "input": "read_input_registers",
}


@dataclass(frozen=True)
class RegisterSpec:
    """A single register/coil to read, keyed by its customer tag."""

    kind: str
    address: int
    count: int = 1
    customer_tag: Optional[str] = None

    @property
    def tag(self) -> str:
        return self.customer_tag or f"{self.kind}:{self.address}"


def parse_register_specs(specs: Iterable[str]) -> list[RegisterSpec]:
    """Parse ``"<kind>:<address>[:<count>]"`` strings into RegisterSpecs."""
    out: list[RegisterSpec] = []
    for spec in specs:
        parts = str(spec).split(":")
        if len(parts) < 2 or parts[0] not in _READ_METHODS:
            raise ValueError(
                f"invalid Modbus register spec {spec!r}; "
                f"expected '<kind>:<address>[:<count>]' with kind in {sorted(_READ_METHODS)}"
            )
        kind = parts[0]
        address = int(parts[1])
        count = int(parts[2]) if len(parts) > 2 else 1
        out.append(RegisterSpec(kind=kind, address=address, count=count))
    return out


class ModbusSource(TelemetrySource):
    """Read-only Modbus TCP source.

    Args:
        host/port/unit: Modbus TCP connection + unit (slave) id.
        registers: RegisterSpecs to read.
        tag_map: Tag map used to normalize the raw register values.
        client: Optional pre-built client (dependency injection for tests).
        timeout: Connection timeout in seconds.
    """

    kind = "modbus"

    def __init__(
        self,
        host: str,
        port: int,
        unit: int,
        registers: Iterable[RegisterSpec],
        tag_map: TagMap,
        *,
        client: Any = None,
        timeout: float = 3.0,
    ) -> None:
        self.host = host
        self.port = port
        self.unit = unit
        self.registers = list(registers)
        self.tag_map = tag_map
        self.timeout = timeout
        self._client = client
        self.name = f"modbus:{host}:{port}"

    def _build_client(self) -> Any:
        if self._client is not None:
            return self._client
        from pymodbus.client import ModbusTcpClient  # lazy: optional dependency

        return ModbusTcpClient(self.host, port=self.port, timeout=self.timeout)

    def _connect(self, client: Any) -> None:
        connect = getattr(client, "connect", None)
        if connect is not None and connect() is False:
            raise SourceUnavailable(f"Modbus device unreachable at {self.host}:{self.port}")

    @staticmethod
    def _close(client: Any) -> None:
        close = getattr(client, "close", None)
        if close is not None:
            close()

    def _read_one(self, client: Any, spec: RegisterSpec) -> Any:
        """Invoke the appropriate READ function code for a register spec."""
        method = getattr(client, _READ_METHODS[spec.kind])
        response = method(spec.address, count=spec.count, slave=self.unit)
        if getattr(response, "isError", lambda: False)():
            raise SourceUnavailable(f"Modbus read error for {spec.tag}: {response}")
        if spec.kind in ("coil", "discrete"):
            bits = getattr(response, "bits", [])
            return 1.0 if (bits and bits[0]) else 0.0
        registers = getattr(response, "registers", [])
        if not registers:
            raise SourceUnavailable(f"Modbus read returned no registers for {spec.tag}")
        return registers[0]

    def read_raw(self) -> list[RawReading]:
        client = self._build_client()
        self._connect(client)
        try:
            raws: list[RawReading] = []
            for spec in self.registers:
                value = self._read_one(client, spec)
                raws.append(RawReading(customer_tag=spec.tag, value=value))
            return raws
        finally:
            self._close(client)

    def read_latest(self) -> list[TelemetryReading]:
        return normalize(self.read_raw(), self.tag_map).readings

    def probe(self) -> None:
        client = self._build_client()
        try:
            self._connect(client)
        except SourceUnavailable:
            raise
        except Exception as exc:
            raise SourceUnavailable(f"Modbus device unreachable: {exc}") from exc
        finally:
            self._close(client)

    def describe(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "unit": self.unit,
            "register_count": len(self.registers),
            "tag_map": self.tag_map.map_id,
        }
