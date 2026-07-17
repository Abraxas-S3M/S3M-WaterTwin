"""Historian telemetry source (read-only REST / SQL / CSV pull).

Pulls historized process values from a plant historian and maps them onto the
canonical model via the tag-normalization layer. Three read-only access modes
are supported:

* ``csv``  -- read a CSV export (columns: ``tag,value[,timestamp,quality]``);
* ``rest`` -- HTTP GET a JSON payload of readings;
* ``sql``  -- run a single read-only ``SELECT`` returning ``tag, value``.

Every mode only *pulls* data. The SQL mode accepts SELECT statements only (any
other statement is refused), the REST mode issues GET only, and the CSV mode
opens files read-only. Nothing here mutates the historian or any control system.
"""

from __future__ import annotations

import csv
from typing import Any, Optional, Sequence

from canonical_water_model import TelemetryReading

from ..tag_normalization import RawReading, TagMap, normalize
from .base import SourceUnavailable, TelemetrySource

_SELECT_PREFIXES = ("select", "with")


def _rows_to_raw(rows: Sequence[dict]) -> list[RawReading]:
    raws: list[RawReading] = []
    for row in rows:
        tag = row.get("tag") or row.get("customer_tag")
        if tag is None:
            continue
        raws.append(
            RawReading(
                customer_tag=str(tag),
                value=row.get("value"),
                timestamp=row.get("timestamp"),
                quality=row.get("quality"),
            )
        )
    return raws


class HistorianSource(TelemetrySource):
    """Read-only historian pull source (CSV / REST / SQL)."""

    kind = "historian"

    def __init__(
        self,
        tag_map: TagMap,
        *,
        access: str = "csv",
        csv_path: Optional[str] = None,
        url: Optional[str] = None,
        dsn: Optional[str] = None,
        query: Optional[str] = None,
        http_client: Any = None,
        timeout: float = 5.0,
    ) -> None:
        self.tag_map = tag_map
        self.access = access.strip().lower()
        self.csv_path = csv_path
        self.url = url
        self.dsn = dsn
        self.query = query
        self.timeout = timeout
        self._http_client = http_client
        self.name = f"historian:{self.access}"
        if self.access not in ("csv", "rest", "sql"):
            raise ValueError(f"unknown historian access mode {self.access!r}")
        if self.access == "sql" and query and not self._is_read_only(query):
            raise ValueError("historian SQL access accepts read-only SELECT statements only")

    @staticmethod
    def _is_read_only(query: str) -> bool:
        return query.strip().lower().lstrip("(").startswith(_SELECT_PREFIXES)

    # --- CSV -----------------------------------------------------------------
    def _read_csv(self) -> list[RawReading]:
        if not self.csv_path:
            raise SourceUnavailable("historian CSV path not configured")
        try:
            with open(self.csv_path, "r", encoding="utf-8", newline="") as fh:
                return _rows_to_raw(list(csv.DictReader(fh)))
        except FileNotFoundError as exc:
            raise SourceUnavailable(f"historian CSV not found: {self.csv_path}") from exc

    # --- REST ----------------------------------------------------------------
    def _read_rest(self) -> list[RawReading]:
        if not self.url:
            raise SourceUnavailable("historian REST url not configured")
        client = self._http_client
        try:
            if client is None:
                import httpx  # lazy: already a service dependency

                response = httpx.get(self.url, timeout=self.timeout)
            else:
                response = client.get(self.url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise SourceUnavailable(f"historian REST pull failed: {exc}") from exc
        if isinstance(payload, dict) and "readings" in payload:
            payload = payload["readings"]
        if isinstance(payload, dict):
            # Bare {tag: value} mapping.
            return [RawReading(customer_tag=str(k), value=v) for k, v in payload.items()]
        if isinstance(payload, list):
            return _rows_to_raw(payload)
        raise SourceUnavailable("historian REST payload is not a list or object")

    # --- SQL -----------------------------------------------------------------
    def _read_sql(self) -> list[RawReading]:
        if not self.dsn or not self.query:
            raise SourceUnavailable("historian SQL dsn/query not configured")
        if not self._is_read_only(self.query):
            raise SourceUnavailable("historian SQL access accepts SELECT statements only")
        try:
            import psycopg  # lazy: already a service dependency

            with psycopg.connect(self.dsn, connect_timeout=int(self.timeout)) as conn:
                with conn.cursor() as cur:
                    cur.execute(self.query)
                    columns = [c.name for c in cur.description] if cur.description else []
                    rows = [dict(zip(columns, r)) for r in cur.fetchall()]
        except Exception as exc:
            raise SourceUnavailable(f"historian SQL pull failed: {exc}") from exc
        return _rows_to_raw(rows)

    def read_raw(self) -> list[RawReading]:
        if self.access == "csv":
            return self._read_csv()
        if self.access == "rest":
            return self._read_rest()
        return self._read_sql()

    def read_latest(self) -> list[TelemetryReading]:
        return normalize(self.read_raw(), self.tag_map).readings

    def probe(self) -> None:
        # A probe is a real (read-only) pull: it proves the feed is reachable.
        self.read_raw()

    def describe(self) -> dict:
        target = {"csv": self.csv_path, "rest": self.url, "sql": "<dsn>"}.get(self.access)
        return {
            "kind": self.kind,
            "name": self.name,
            "access": self.access,
            "target": target,
            "tag_map": self.tag_map.map_id,
        }
