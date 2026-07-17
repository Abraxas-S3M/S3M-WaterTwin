"""Deployment profile enforcement (edge / XiiD-ready topology).

WaterTwin is already an advisory, read-only conductor: it never writes to a
control system. This module adds a second, *directional* guarantee on top of the
existing read-only posture, expressed by the ``DEPLOYMENT_PROFILE`` config flag:

``standard``
    The platform may open a connection *toward* the OT side to pull telemetry
    through the strictly read-only OT connectors (OPC UA / Modbus / historian
    REST or SQL). The reads are still read-only; the platform simply initiates
    the connection.

``one_way_diode``
    A one-way / data-diode profile (SealedTunnel / XiiD-style). The edge gateway
    PUSHES telemetry to the platform and the platform NEVER initiates a
    connection toward the OT side. Every platform->OT request code path is
    disabled at startup and refuses to run (**fail-closed**): a misconfiguration
    that would have the platform reach into the OT zone raises rather than
    silently degrading. Only the synthetic source and gateway-pushed / local
    file-drop feeds are permitted.

The guarantee here is about *direction of connection initiation*, which is the
property a data diode / one-way conduit enforces at the network layer. This
module makes the same property explicit and testable in the application layer so
the two cannot drift apart. See ``docs/deployment/edge-xiid-reference.md`` and
``docs/security/control-boundaries.md``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("watertwin.deployment")

#: Standard profile: platform-initiated read-only OT pulls are permitted.
STANDARD = "standard"

#: One-way / data-diode profile: platform never initiates toward OT (fail-closed).
ONE_WAY_DIODE = "one_way_diode"

#: All valid deployment profiles.
PROFILES = (STANDARD, ONE_WAY_DIODE)

#: OT source kinds that always require the platform to initiate a connection
#: toward the OT zone (i.e. a platform->OT request path). These are forbidden
#: under the one-way / data-diode profile.
_ALWAYS_PLATFORM_INITIATED = frozenset({"opcua", "modbus"})

#: Historian access kinds that require the platform to reach out to an OT-side
#: system. ``csv`` reads a local file the gateway drops onto the platform, so it
#: is *not* a platform->OT request path.
_PLATFORM_INITIATED_HISTORIAN = frozenset({"rest", "sql"})


class OneWayDiodeViolation(RuntimeError):
    """Raised when a platform->OT request path is attempted under one_way_diode.

    This is a fail-closed error: the platform refuses to open a connection toward
    the OT zone in a one-way / data-diode deployment, rather than degrading to a
    different behaviour silently.
    """


def get_profile(config) -> str:
    """Return the normalized deployment profile from ``config``.

    An unknown profile fails closed to :data:`ONE_WAY_DIODE` (the most
    restrictive posture) and logs a warning, so a typo can never accidentally
    open a platform->OT path.
    """
    profile = (getattr(config, "DEPLOYMENT_PROFILE", STANDARD) or STANDARD).strip().lower()
    if profile not in PROFILES:
        logger.warning(
            "Unknown DEPLOYMENT_PROFILE %r; failing closed to %r (valid: %s)",
            profile,
            ONE_WAY_DIODE,
            list(PROFILES),
        )
        return ONE_WAY_DIODE
    return profile


def is_one_way_diode(config) -> bool:
    """True when the deployment must never initiate a connection toward OT."""
    return get_profile(config) == ONE_WAY_DIODE


def is_platform_initiated_ot(source_kind: str, config) -> bool:
    """Whether selecting ``source_kind`` makes the platform initiate to the OT side.

    ``opcua``/``modbus`` always do. ``historian`` does when its access kind is
    ``rest`` or ``sql`` (it reaches out to an OT-side service); a ``csv`` drop is
    a gateway-push / file feed and does not.
    """
    kind = (source_kind or "").strip().lower()
    if kind in _ALWAYS_PLATFORM_INITIATED:
        return True
    if kind == "historian":
        access = (getattr(config, "OT_HISTORIAN_KIND", "csv") or "csv").strip().lower()
        return access in _PLATFORM_INITIATED_HISTORIAN
    return False


def assert_source_allowed(source_kind: str, config) -> None:
    """Fail-closed guard for telemetry-source selection.

    Raises :class:`OneWayDiodeViolation` if the one-way / data-diode profile is
    active and ``source_kind`` would have the platform initiate a connection
    toward the OT zone.
    """
    if is_one_way_diode(config) and is_platform_initiated_ot(source_kind, config):
        raise OneWayDiodeViolation(
            f"DEPLOYMENT_PROFILE={ONE_WAY_DIODE} forbids the platform initiating a "
            f"connection toward OT, but OT_SOURCE={source_kind!r} is a platform->OT "
            "pull. In a one-way/data-diode deployment the edge gateway must PUSH "
            "telemetry (use OT_SOURCE=synthetic or a gateway-pushed / historian:csv "
            "file feed). See docs/deployment/edge-xiid-reference.md."
        )


def guard_outbound_ot(operation: str, config) -> None:
    """Fail-closed runtime guard for any platform-initiated OT request.

    Call this immediately before opening a connection toward the OT side (e.g.
    inside an OT connector's ``probe``/``read``). Under the one-way / data-diode
    profile it raises :class:`OneWayDiodeViolation`; under ``standard`` it is a
    no-op. This is defence-in-depth on top of :func:`assert_source_allowed`.
    """
    if is_one_way_diode(config):
        raise OneWayDiodeViolation(
            f"DEPLOYMENT_PROFILE={ONE_WAY_DIODE} forbids platform->OT request "
            f"{operation!r}: the platform must never initiate a connection toward "
            "the OT zone in a one-way/data-diode deployment."
        )


def enforce_startup(config) -> str:
    """Validate the deployment profile at startup (fail-closed).

    Returns the active profile. Under :data:`ONE_WAY_DIODE`, raises
    :class:`OneWayDiodeViolation` if the configured telemetry source is a
    platform->OT pull, preventing the service from starting in a configuration
    that would break the one-way guarantee.
    """
    profile = get_profile(config)
    requested = (getattr(config, "OT_SOURCE", "synthetic") or "synthetic").strip().lower()
    if profile == ONE_WAY_DIODE:
        assert_source_allowed(requested, config)
        logger.info(
            "DEPLOYMENT_PROFILE=%s active: platform->OT request paths are DISABLED "
            "(fail-closed). Telemetry must arrive via gateway push. Active source=%r.",
            profile,
            requested,
        )
    else:
        logger.info("DEPLOYMENT_PROFILE=%s active.", profile)
    return profile
