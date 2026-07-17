"""D1 analytics models for the reference RO train (advisory, read-only).

Three concrete D1 models are implemented against the ``watertwin_models`` (D1)
framework. Each one REUSES existing canonical physics / service layers rather
than re-deriving them, carries a full :class:`~watertwin_models.ModelSpec`
(inputs, outputs, baseline, reused components, preliminary thresholds, drift +
calibration configuration), and ships a synthetic back-test dataset and a
benchmark scaffold:

* :mod:`.pump_condition` -- Model 1: HP-pump condition -> explainable pump-health
  index + cavitation probability (reuses the NPSH / pump-curve / component-health
  physics; nothing duplicated).
* :mod:`.membrane_fouling` -- Model 2: membrane fouling & salt passage (reuses the
  existing Membrane + Water-Quality layer; nothing re-created).
* :mod:`.cartridge_filter` -- Model 3: cartridge-filter replacement.

Every model is advisory: outputs carry the read-only control boundary and
``provenance = preliminary``, all thresholds are preliminary pending customer
calibration, and no module writes to any control system.
"""

from __future__ import annotations

from . import cartridge_filter, membrane_fouling, pump_condition
from .base import ModelAdapter

#: Registry of the D1 models keyed by their ``model_id``.
MODELS: dict[str, ModelAdapter] = {
    pump_condition.ADAPTER.spec.model_id: pump_condition.ADAPTER,
    membrane_fouling.ADAPTER.spec.model_id: membrane_fouling.ADAPTER,
    cartridge_filter.ADAPTER.spec.model_id: cartridge_filter.ADAPTER,
}


def list_model_ids() -> list[str]:
    """Return the ids of the registered D1 models."""
    return list(MODELS)


def get_adapter(model_id: str) -> ModelAdapter:
    """Return the adapter for ``model_id`` (raises ``KeyError`` if unknown)."""
    return MODELS[model_id]


__all__ = [
    "MODELS",
    "ModelAdapter",
    "cartridge_filter",
    "get_adapter",
    "list_model_ids",
    "membrane_fouling",
    "pump_condition",
]
