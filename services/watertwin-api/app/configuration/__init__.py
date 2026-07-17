"""Versioned, approval-gated customer configuration service.

Distinct from :mod:`app.config` (the environment-variable loader). This package
provides a versioned, immutable-on-publish configuration store for customer
onboarding data (asset hierarchy, tag discovery/mapping, engineering units,
alarm thresholds, rated equipment, pump curves, membrane models, process stages,
sampling points, lab methods, compliance limits, role assignments).

Configuration is declarative data only: nothing here writes to a control system,
so the platform's advisory / read-only control invariant is unchanged.
"""

from __future__ import annotations

from ..store import Store
from .router import configure, get_config_service, router
from .service import (
    ConfigConflictError,
    ConfigError,
    ConfigNotFoundError,
    ConfigService,
    ConfigValidationError,
    UnknownEntityError,
)

__all__ = [
    "router",
    "configure",
    "get_config_service",
    "init_app",
    "ConfigService",
    "ConfigError",
    "ConfigConflictError",
    "ConfigNotFoundError",
    "ConfigValidationError",
    "UnknownEntityError",
]


def init_app(app, store: Store) -> ConfigService:
    """Bind a :class:`ConfigService` (sharing ``store``) and mount the router."""
    service = ConfigService(store)
    configure(service)
    app.include_router(router)
    return service
