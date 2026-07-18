"""Provenance labels and CRS constants for bulk file imports.

These labels are deliberately **distinct** from the canonical
:class:`canonical_water_model.DataProvenance` values. A file that a customer
hands us is not, by the mere act of import, ``measured`` platform data and is
never ``calibrated``. It is *customer-asserted* until the documented validation
process (with a named engineer's sign-off) says otherwise. Keeping these as their
own label set makes it impossible for an import to accidentally stamp data with a
canonical provenance that implies validation.
"""

from __future__ import annotations

from enum import Enum

#: Platform coordinate reference system. All staged geometry is reprojected to
#: this CRS (WGS84 lon/lat, RFC 7946), matching ``network_twin`` geo-referencing.
PLATFORM_CRS = "EPSG:4326"


class IngestProvenance(str, Enum):
    """Provenance for data admitted through the bulk-import staging path."""

    #: Historian time-series a customer exported and measured on their plant.
    customer_measured = "customer_measured"
    #: Geospatial layers a customer supplied (network geometry, asset overlays).
    customer_supplied = "customer_supplied"
