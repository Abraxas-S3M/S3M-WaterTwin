"""S3M-WaterTwin: an advisory (read/recommend-only) water-plant digital twin."""

__version__ = "0.6.0"
"""S3M-WaterTwin API service package."""

__version__ = "0.5.0"
"""WaterTwin API domain package for a reverse-osmosis desalination digital twin."""

from watertwin.models import (
    Asset,
    AssetType,
    Criticality,
    RatedData,
    SamplingPoint,
    TelemetryReading,
    WaterStream,
)

__all__ = [
    "Asset",
    "AssetType",
    "Criticality",
    "RatedData",
    "SamplingPoint",
    "TelemetryReading",
    "WaterStream",
]
"""S3M-WaterTwin API package."""

__all__ = ["analytics"]
__version__ = "0.1.0"
