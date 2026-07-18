"""Deployment-profile gate for the ingest service (fail-closed).

Mirrors ``services/watertwin-api/app/deployment.py``: under
``DEPLOYMENT_PROFILE=one_way_diode`` (a one-way / data-diode critical-
infrastructure deployment) inbound file ingestion is DISABLED and the dashboard
hides the ingestion nav item. An unknown profile fails closed to
``one_way_diode`` so a typo can never accidentally enable inbound ingestion.
"""

from __future__ import annotations

import logging

from . import config

logger = logging.getLogger("watertwin.ingest.deployment")

STANDARD = "standard"
ONE_WAY_DIODE = "one_way_diode"
PROFILES = (STANDARD, ONE_WAY_DIODE)


class IngestionDisabled(Exception):
    """Raised when ingestion is attempted while it is disabled by profile."""


def get_profile(profile: str | None = None) -> str:
    """Return the normalized deployment profile (unknown -> fail closed)."""
    value = (profile if profile is not None else config.DEPLOYMENT_PROFILE) or STANDARD
    value = value.strip().lower()
    if value not in PROFILES:
        logger.warning(
            "Unknown DEPLOYMENT_PROFILE %r; failing closed to %r", value, ONE_WAY_DIODE
        )
        return ONE_WAY_DIODE
    return value


def ingestion_enabled(profile: str | None = None) -> bool:
    """True iff inbound file ingestion is enabled under the active profile."""
    return get_profile(profile) == STANDARD


def nav_item_visible(profile: str | None = None) -> bool:
    """True iff the dashboard should show the ingestion nav item."""
    return ingestion_enabled(profile)


def assert_ingestion_enabled(profile: str | None = None) -> None:
    """Raise :class:`IngestionDisabled` when ingestion is off for this profile."""
    if not ingestion_enabled(profile):
        raise IngestionDisabled(
            f"DEPLOYMENT_PROFILE={get_profile(profile)} disables inbound file "
            "ingestion (one-way/data-diode deployment). Telemetry must arrive via "
            "the edge gateway push path; the ingestion nav item is hidden."
        )
