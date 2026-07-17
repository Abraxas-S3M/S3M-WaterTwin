"""A1 config store: configurable regulatory-compliance limits.

A small, deployment-configurable store for the per-parameter regulatory limits
(e.g. turbidity, conductivity, chlorine residual) that drive the advisory
compliance screening + regulatory report. It ships with documented defaults and
is configurable at deploy time (a JSON file or an inline JSON array of limit
overrides) and at runtime (``upsert``/``set_limit``) so operators can tune the
limits to their jurisdiction without a code change.

Nothing here writes to any control system. The limits only parameterise
advisory compliance screening; every downstream artifact stays read-only and
carries the standard disclaimer.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Iterable

from canonical_water_model import ComplianceLimit, LimitBound

from . import config

logger = logging.getLogger("watertwin.config_store")


# The documented default regulatory limits. These are screening defaults on the
# finished/product water (WHO GDWQ / US EPA / EU DWD orders of magnitude); a
# deployment overrides them for its own jurisdiction via the A1 config store.
_DEFAULT_LIMITS: list[ComplianceLimit] = [
    ComplianceLimit(
        parameter="turbidity_ntu",
        display_name="Turbidity",
        unit="NTU",
        limit=0.3,
        bound=LimitBound.max,
        stage="finished",
        basis="US EPA SWTR / WHO GDWQ (≤0.3 NTU, 95th percentile)",
    ),
    ComplianceLimit(
        parameter="conductivity_us_cm",
        display_name="Conductivity",
        unit="µS/cm",
        limit=1600.0,
        bound=LimitBound.max,
        stage="finished",
        basis="EU Drinking Water Directive (2500 µS/cm) — plant target margin",
    ),
    ComplianceLimit(
        parameter="free_chlorine_mg_l",
        display_name="Chlorine residual (free)",
        unit="mg/L",
        limit=0.2,
        bound=LimitBound.min,
        stage="finished",
        basis="WHO GDWQ (≥0.2 mg/L free residual at point of delivery)",
    ),
    ComplianceLimit(
        parameter="boron_mg_l",
        display_name="Boron",
        unit="mg/L",
        limit=2.4,
        bound=LimitBound.max,
        stage="finished",
        basis="WHO GDWQ 4th ed. (2.4 mg/L)",
    ),
    ComplianceLimit(
        parameter="tds_mg_l",
        display_name="Total dissolved solids",
        unit="mg/L",
        limit=600.0,
        bound=LimitBound.max,
        stage="finished",
        basis="WHO GDWQ aesthetic guidance (≈600 mg/L) — plant target",
    ),
    ComplianceLimit(
        parameter="toc_mg_l",
        display_name="Total organic carbon",
        unit="mg/L",
        limit=2.0,
        bound=LimitBound.max,
        stage="finished",
        basis="Operator target for finished-water organics",
    ),
]


def default_limits() -> list[ComplianceLimit]:
    """Return a fresh copy of the documented default compliance limits."""
    return [limit.model_copy(deep=True) for limit in _DEFAULT_LIMITS]


def _coerce_limit(raw: Any) -> ComplianceLimit:
    """Coerce a mapping/`ComplianceLimit` into a validated `ComplianceLimit`."""
    if isinstance(raw, ComplianceLimit):
        return raw.model_copy(deep=True)
    if isinstance(raw, dict):
        return ComplianceLimit(**raw)
    raise TypeError(f"cannot coerce {type(raw)!r} into a ComplianceLimit")


class ConfigStore:
    """In-memory, thread-safe store of configurable compliance limits (A1).

    Seeded with the documented defaults, then layered with any deployment
    overrides (a JSON file and/or inline JSON) and, finally, any runtime
    ``upsert``. Overrides are keyed by ``parameter`` so a partial override
    replaces just that limit and leaves the other defaults intact.
    """

    def __init__(
        self,
        *,
        load_env: bool = True,
        overrides: Iterable[Any] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._limits: dict[str, ComplianceLimit] = {}
        self._seed_defaults()
        if load_env:
            self._apply_env()
        if overrides:
            self.upsert(overrides)

    def _seed_defaults(self) -> None:
        self._limits = {limit.parameter: limit for limit in default_limits()}

    def _apply_env(self) -> None:
        """Layer deployment overrides from the configured file + inline JSON."""
        if config.COMPLIANCE_LIMITS_PATH:
            try:
                with open(config.COMPLIANCE_LIMITS_PATH, encoding="utf-8") as fh:
                    self.upsert(json.load(fh))
            except (OSError, ValueError, TypeError) as exc:  # pragma: no cover - config error path
                logger.warning(
                    "ignoring unreadable compliance-limits file",
                    extra={"path": config.COMPLIANCE_LIMITS_PATH, "error": str(exc)},
                )
        if config.COMPLIANCE_LIMITS_JSON:
            try:
                self.upsert(json.loads(config.COMPLIANCE_LIMITS_JSON))
            except (ValueError, TypeError) as exc:  # pragma: no cover - config error path
                logger.warning(
                    "ignoring invalid WATERTWIN_COMPLIANCE_LIMITS json",
                    extra={"error": str(exc)},
                )

    # -- reads ---------------------------------------------------------------

    def limits(self, *, enabled_only: bool = True) -> list[ComplianceLimit]:
        """Return the configured limits (enabled-only by default), sorted."""
        with self._lock:
            items = [limit.model_copy(deep=True) for limit in self._limits.values()]
        if enabled_only:
            items = [limit for limit in items if limit.enabled]
        items.sort(key=lambda limit: (limit.stage, limit.parameter))
        return items

    def get_limit(self, parameter: str) -> ComplianceLimit | None:
        """Return one configured limit by canonical parameter key, if present."""
        with self._lock:
            limit = self._limits.get(parameter)
            return limit.model_copy(deep=True) if limit else None

    # -- writes (config only; never a control-write path) --------------------

    def set_limit(self, limit: Any) -> ComplianceLimit:
        """Insert or replace one compliance limit; returns the stored copy."""
        coerced = _coerce_limit(limit)
        with self._lock:
            self._limits[coerced.parameter] = coerced
        return coerced.model_copy(deep=True)

    def upsert(self, limits: Iterable[Any]) -> None:
        """Insert or replace many compliance limits (keyed by ``parameter``)."""
        for limit in limits:
            self.set_limit(limit)

    def remove(self, parameter: str) -> None:
        """Remove a configured limit by parameter key (no-op if absent)."""
        with self._lock:
            self._limits.pop(parameter, None)

    def reset(self) -> None:
        """Restore the documented defaults + deployment overrides (test aid)."""
        with self._lock:
            self._seed_defaults()
            self._apply_env()
