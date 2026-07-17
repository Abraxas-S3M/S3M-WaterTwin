"""OPC UA telemetry source (asyncua CLIENT ONLY, strictly read-only).

Connects to an OPC UA server as a *client*, reads the value of each configured
NodeId, and maps the readings onto the canonical model via the tag-normalization
layer. It only ever **reads** node values (``read_value``); it never calls any
node-write / attribute-set method, and it never mutates the server address
space. The read-only guard test enforces this invariant.
"""

from __future__ import annotations

import asyncio
from typing import Any, Sequence

from canonical_water_model import TelemetryReading

from ..tag_normalization import RawReading, TagMap, normalize
from .base import SourceUnavailable, TelemetrySource


class OpcUaSource(TelemetrySource):
    """Read-only OPC UA client source.

    Args:
        endpoint: OPC UA server endpoint URL (``opc.tcp://host:4840``).
        node_ids: NodeIds to read; each NodeId string is also the customer tag.
        tag_map: Tag map used to normalize the raw node values.
        client: Optional pre-built async client (dependency injection for tests).
        timeout: Per-operation timeout in seconds.
    """

    kind = "opcua"

    def __init__(
        self,
        endpoint: str,
        node_ids: Sequence[str],
        tag_map: TagMap,
        *,
        client: Any = None,
        timeout: float = 5.0,
    ) -> None:
        self.endpoint = endpoint
        self.node_ids = list(node_ids)
        self.tag_map = tag_map
        self.timeout = timeout
        self._client = client
        self.name = f"opcua:{endpoint}"

    def _build_client(self) -> Any:
        if self._client is not None:
            return self._client
        from asyncua import Client  # lazy: optional dependency

        return Client(url=self.endpoint, timeout=self.timeout)

    async def _read_raw_async(self) -> list[RawReading]:
        client = self._build_client()
        await client.connect()
        try:
            raws: list[RawReading] = []
            for node_id in self.node_ids:
                node = client.get_node(node_id)
                # READ-ONLY: fetch the current value of the node.
                value = await node.read_value()
                raws.append(RawReading(customer_tag=str(node_id), value=value))
            return raws
        finally:
            await client.disconnect()

    async def _probe_async(self) -> None:
        client = self._build_client()
        await client.connect()
        await client.disconnect()

    def read_raw(self) -> list[RawReading]:
        try:
            return asyncio.run(self._read_raw_async())
        except Exception as exc:  # pragma: no cover - network dependent
            raise SourceUnavailable(f"OPC UA read failed: {exc}") from exc

    def read_latest(self) -> list[TelemetryReading]:
        return normalize(self.read_raw(), self.tag_map).readings

    def probe(self) -> None:
        try:
            asyncio.run(self._probe_async())
        except Exception as exc:
            raise SourceUnavailable(f"OPC UA endpoint unreachable: {exc}") from exc

    def describe(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "endpoint": self.endpoint,
            "node_count": len(self.node_ids),
            "tag_map": self.tag_map.map_id,
        }
