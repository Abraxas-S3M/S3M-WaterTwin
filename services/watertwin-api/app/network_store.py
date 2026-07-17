"""Geospatial network-twin store: PostGIS-backed with an in-memory fallback.

Persists the network twin (nodes/links + geometry, linked to canonical asset
ids) into PostGIS when a spatially-enabled Postgres is reachable, and falls back
to a pure in-memory / GeoJSON store otherwise so the service and its tests run
with no infrastructure. This mirrors the graceful-degradation contract of
:class:`app.store.Store`.

When PostGIS is available, geometry is stored in a ``geometry(Geometry, 4326)``
column (built from GeoJSON via ``ST_GeomFromGeoJSON``) and spatial queries use
native operators (``<->`` KNN, ``ST_Distance``). The in-memory path computes the
same answers in Python (great-circle distance) from the stored GeoJSON so both
paths are behaviourally equivalent for callers.

Nothing here is a control-write path; it persists advisory, synthetic geometry
only.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

from network_twin import NetworkElement, feature_collection, nearest_elements

logger = logging.getLogger("watertwin.network_store")

# Spatial table for the network twin. Created only when PostGIS is present; the
# geometry column uses SRID 4326 (WGS84) to match the emitted GeoJSON.
_CREATE_NETWORK_ELEMENT = """
CREATE TABLE IF NOT EXISTS network_element (
    element_id         TEXT PRIMARY KEY,
    network_id         TEXT NOT NULL DEFAULT 'ro-handoff',
    element_type       TEXT NOT NULL,
    kind               TEXT NOT NULL,
    canonical_asset_id TEXT NOT NULL,
    canonical_link     BOOLEAN NOT NULL DEFAULT FALSE,
    start_node         TEXT,
    end_node           TEXT,
    properties         JSONB NOT NULL DEFAULT '{}'::jsonb,
    geojson            JSONB NOT NULL DEFAULT '{}'::jsonb,
    geom               geometry(Geometry, 4326)
);
"""

_CREATE_NETWORK_INDEXES = (
    "CREATE INDEX IF NOT EXISTS network_element_geom_idx ON network_element USING GIST (geom)",
    "CREATE INDEX IF NOT EXISTS network_element_asset_idx ON network_element (canonical_asset_id)",
    "CREATE INDEX IF NOT EXISTS network_element_type_idx ON network_element (element_type)",
)


class NetworkStore:
    """Network-twin persistence with PostGIS + graceful in-memory fallback."""

    def __init__(self, database_url: str | None = None, *, connect: bool = True) -> None:
        self.database_url = database_url or None
        self.db_connected = False
        self.spatial_enabled = False
        self._conn: Any = None
        self._lock = threading.RLock()

        # In-memory mirror keyed by element_id (used whenever PostGIS is absent).
        self._mem: dict[str, NetworkElement] = {}

        if connect and self.database_url:
            self._try_connect(self.database_url)

    # -- connection lifecycle -------------------------------------------------

    def _try_connect(self, database_url: str) -> None:
        try:  # pragma: no cover - exercised only with a real PostGIS database
            import psycopg

            conn = psycopg.connect(database_url, autocommit=True)
            spatial = False
            with conn.cursor() as cur:
                try:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
                    spatial = True
                except Exception as exc:
                    logger.warning(
                        "PostGIS extension unavailable; spatial features disabled",
                        extra={"error": str(exc)},
                    )
                if spatial:
                    cur.execute(_CREATE_NETWORK_ELEMENT)
                    for stmt in _CREATE_NETWORK_INDEXES:
                        cur.execute(stmt)
            self._conn = conn
            self.db_connected = True
            self.spatial_enabled = spatial
            logger.info(
                "network store connected",
                extra={"db_connected": True, "spatial_enabled": spatial},
            )
        except Exception as exc:  # pragma: no cover - real DB only
            self._conn = None
            self.db_connected = False
            self.spatial_enabled = False
            logger.warning(
                "network store falling back to in-memory mode",
                extra={"db_connected": False, "error": str(exc)},
            )

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:  # pragma: no cover - real DB only
                try:
                    self._conn.close()
                finally:
                    self._conn = None
                    self.db_connected = False
                    self.spatial_enabled = False

    # -- persistence ----------------------------------------------------------

    def _use_db(self) -> bool:
        return self.db_connected and self.spatial_enabled and self._conn is not None

    def load_elements(self, elements: list[NetworkElement]) -> int:
        """Replace the stored twin with ``elements``. Returns the count stored."""
        with self._lock:
            if self._use_db():
                try:  # pragma: no cover - real DB only
                    from psycopg.types.json import Jsonb

                    with self._conn.cursor() as cur:
                        cur.execute("TRUNCATE network_element")
                        for e in elements:
                            cur.execute(
                                "INSERT INTO network_element "
                                "(element_id, element_type, kind, canonical_asset_id, "
                                " canonical_link, start_node, end_node, properties, geojson, geom) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
                                " ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))",
                                (
                                    e.element_id,
                                    e.element_type.value,
                                    e.kind.value,
                                    e.canonical_asset_id,
                                    e.canonical_link,
                                    e.start_node,
                                    e.end_node,
                                    Jsonb(e.properties),
                                    Jsonb(e.to_feature()),
                                    json.dumps(e.geometry),
                                ),
                            )
                    return len(elements)
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning(
                        "network load failed; mirroring to memory",
                        extra={"error": str(exc)},
                    )
            self._mem = {e.element_id: e for e in elements}
            return len(self._mem)

    def _all(self) -> list[NetworkElement]:
        if self._use_db():
            try:  # pragma: no cover - real DB only
                with self._conn.cursor() as cur:
                    cur.execute("SELECT geojson FROM network_element ORDER BY element_id")
                    rows = cur.fetchall()
                return [_element_from_feature(r[0]) for r in rows]
            except Exception as exc:  # pragma: no cover - real DB only
                logger.warning("network read failed; using memory", extra={"error": str(exc)})
        return list(self._mem.values())

    def count(self) -> int:
        with self._lock:
            return len(self._all())

    def features(
        self,
        *,
        element_type: Optional[str] = None,
        kind: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Return a GeoJSON FeatureCollection, optionally filtered by type/kind."""
        with self._lock:
            elements = self._all()
        if element_type:
            elements = [e for e in elements if e.element_type.value == element_type]
        if kind:
            elements = [e for e in elements if e.kind.value == kind]
        return feature_collection(elements, metadata=metadata)

    def by_asset(self, asset_id: str) -> list[NetworkElement]:
        """Return elements linked to ``asset_id`` (canonical id or element id)."""
        with self._lock:
            if self._use_db():
                try:  # pragma: no cover - real DB only
                    with self._conn.cursor() as cur:
                        cur.execute(
                            "SELECT geojson FROM network_element "
                            "WHERE canonical_asset_id = %s OR element_id = %s "
                            "ORDER BY element_id",
                            (asset_id, asset_id),
                        )
                        rows = cur.fetchall()
                    return [_element_from_feature(r[0]) for r in rows]
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("asset lookup failed; using memory", extra={"error": str(exc)})
            return [
                e
                for e in self._mem.values()
                if e.canonical_asset_id == asset_id or e.element_id == asset_id
            ]

    def nearest(self, lon: float, lat: float, *, limit: int = 1) -> list[dict[str, Any]]:
        """Return the ``limit`` nearest elements to ``(lon, lat)`` with distances."""
        with self._lock:
            if self._use_db():
                try:  # pragma: no cover - real DB only
                    with self._conn.cursor() as cur:
                        cur.execute(
                            "SELECT geojson, "
                            "ST_Distance(geom::geography, "
                            "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) AS d "
                            "FROM network_element ORDER BY d ASC LIMIT %s",
                            (lon, lat, limit),
                        )
                        rows = cur.fetchall()
                    return [
                        {"element": _element_from_feature(r[0]), "distance_m": round(float(r[1]), 3)}
                        for r in rows
                    ]
                except Exception as exc:  # pragma: no cover - real DB only
                    logger.warning("nearest query failed; using memory", extra={"error": str(exc)})
            return nearest_elements(list(self._mem.values()), lon, lat, limit=limit)

    def describe(self) -> dict[str, Any]:
        return {
            "db_connected": self.db_connected,
            "spatial_enabled": self.spatial_enabled,
            "backend": "postgis" if self._use_db() else "in-memory",
            "element_count": self.count(),
        }


def _element_from_feature(feature: dict[str, Any]) -> NetworkElement:
    """Reconstruct a :class:`NetworkElement` from its stored GeoJSON feature."""
    props = dict(feature.get("properties") or {})
    element_id = props.pop("element_id", feature.get("id"))
    element_type = props.pop("element_type")
    kind = props.pop("kind")
    canonical_asset_id = props.pop("canonical_asset_id", element_id)
    canonical_link = props.pop("canonical_link", False)
    node_id = props.pop("node_id", None)
    start_node = props.pop("start_node", None)
    end_node = props.pop("end_node", None)
    return NetworkElement(
        element_id=element_id,
        element_type=element_type,
        kind=kind,
        canonical_asset_id=canonical_asset_id,
        canonical_link=canonical_link,
        node_id=node_id,
        start_node=start_node,
        end_node=end_node,
        geometry=feature.get("geometry") or {},
        properties=props,
    )
