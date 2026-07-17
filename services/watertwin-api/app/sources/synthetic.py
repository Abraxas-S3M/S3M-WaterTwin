"""Synthetic telemetry source -- compatibility shim.

Re-exports the shared :mod:`ot_ingestion.sources.synthetic` and registers the
API's existing synthetic plant (``app.predictive_maintenance.ASSETS``) as the
default synthetic asset provider, so ``SyntheticSource()`` yields exactly the
same telemetry as before the sources were moved to the shared package.
"""

from __future__ import annotations

from ot_ingestion.sources.synthetic import (  # noqa: F401
    BUILTIN_SYNTHETIC_ASSETS,
    SyntheticAsset,
    SyntheticSource,
    register_default_assets_provider,
    unit_for,
)


def _api_synthetic_assets() -> dict:
    """Provide the API's synthetic plant as the default source of truth.

    Imported lazily to avoid an import cycle with the API package (the
    predictive-maintenance module imports the canonical model + engineering
    layers), matching the pre-move lazy-import behaviour.
    """
    from ..predictive_maintenance import ASSETS

    return ASSETS


register_default_assets_provider(_api_synthetic_assets)

__all__ = [
    "BUILTIN_SYNTHETIC_ASSETS",
    "SyntheticAsset",
    "SyntheticSource",
    "register_default_assets_provider",
    "unit_for",
]
