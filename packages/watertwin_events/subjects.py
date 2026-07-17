"""Event subjects + the advisory-only control-boundary guard.

The event bus carries **advisory / notification** service events only. Every
subject describes something that *already happened* (past tense: ``ingested``,
``raised``, ``created``, ``published``, ``appended``) so a subscriber can react,
project, or fan out -- it is never an instruction to *do* something to plant
equipment.

To keep that boundary enforceable (not merely documented) this module defines
the canonical set of published subjects, a list of forbidden *control verbs*,
and :func:`assert_advisory_subject`, which the :class:`~watertwin_events.bus.EventBus`
calls before it will publish or subscribe. A subject that names a control verb
(``command``, ``write``, ``setpoint``, ``start``/``stop`` ...) or that falls
outside the ``watertwin.events.*`` namespace is rejected, so a control command
can never be placed on the bus. The guard test scans :data:`EVENT_SUBJECTS`
with the same primitives.
"""

from __future__ import annotations

import re

#: Root namespace for every advisory service event. Publishing/subscribing is
#: restricted to this namespace so an arbitrary (potentially control) subject
#: can never be used on the bus.
SUBJECT_ROOT = "watertwin.events"

# --- The five advisory service events --------------------------------------

#: Telemetry has been ingested + normalized from a (read-only) source.
TELEMETRY_INGESTED = f"{SUBJECT_ROOT}.telemetry.ingested"
#: An advisory alert (e.g. water-quality) has been raised for operator review.
ALERT_RAISED = f"{SUBJECT_ROOT}.alert.raised"
#: A maintenance work order (predictive-maintenance card) has been created.
WORKORDER_CREATED = f"{SUBJECT_ROOT}.workorder.created"
#: A configuration (e.g. active telemetry source / tag map) has been published.
CONFIG_PUBLISHED = f"{SUBJECT_ROOT}.config.published"
#: An audit event has been appended to the tamper-evident audit trail.
AUDIT_APPENDED = f"{SUBJECT_ROOT}.audit.appended"

#: The canonical registry of every subject the platform publishes. The guard
#: test scans exactly this set for forbidden control verbs.
EVENT_SUBJECTS: frozenset[str] = frozenset(
    {
        TELEMETRY_INGESTED,
        ALERT_RAISED,
        WORKORDER_CREATED,
        CONFIG_PUBLISHED,
        AUDIT_APPENDED,
    }
)

# --- Control-boundary guard -------------------------------------------------

#: Imperative / control verbs. If any appears as a token in a subject the
#: subject is treated as a *control command* and rejected -- the bus is
#: advisory/notification-only and must never carry a control instruction.
FORBIDDEN_CONTROL_VERBS: frozenset[str] = frozenset(
    {
        "command",
        "commands",
        "cmd",
        "control",
        "write",
        "writes",
        "set",
        "setpoint",
        "setpoints",
        "actuate",
        "actuation",
        "start",
        "stop",
        "open",
        "close",
        "override",
        "trip",
        "enable",
        "disable",
        "dispatch",
        "execute",
        "exec",
        "reset",
        "adjust",
        "move",
        "toggle",
        "switch",
        "apply",
        "activate",
        "deactivate",
        "shutdown",
        "startup",
        "manipulate",
        "force",
        "engage",
        "disengage",
        "throttle",
        "modulate",
        "operate",
        "steer",
        "drive",
    }
)

#: Split a subject into lowercase tokens on the usual separators so a control
#: verb is matched as a whole word (``config.setpoint.published`` -> the token
#: ``setpoint``) and never as an accidental substring (``published`` never
#: matches ``publish``, which is not a forbidden verb anyway).
_TOKEN_SPLIT = re.compile(r"[.\-_/:\s]+")


class ControlCommandOnBusError(ValueError):
    """Raised when a control-command subject is published to the advisory bus."""


def tokenize_subject(subject: str) -> set[str]:
    """Return the lowercase token set of a subject (for guard scanning)."""
    return {tok for tok in _TOKEN_SPLIT.split(subject.lower()) if tok}


def forbidden_verbs_in(subject: str) -> set[str]:
    """Return any forbidden control verbs named as tokens in ``subject``."""
    return tokenize_subject(subject) & FORBIDDEN_CONTROL_VERBS


def is_advisory_subject(subject: str) -> bool:
    """Return ``True`` if ``subject`` is a well-formed advisory event subject."""
    if not subject or not isinstance(subject, str):
        return False
    if not subject.startswith(f"{SUBJECT_ROOT}."):
        return False
    return not forbidden_verbs_in(subject)


def assert_advisory_subject(subject: str) -> None:
    """Validate that ``subject`` is advisory/notification-only.

    Raises :class:`ControlCommandOnBusError` if the subject is empty, falls
    outside the ``watertwin.events.*`` namespace, or names a forbidden control
    verb. This is the single choke point the bus uses so a control command can
    never be published or subscribed to.
    """
    if not subject or not isinstance(subject, str):
        raise ControlCommandOnBusError(f"invalid event subject: {subject!r}")
    forbidden = forbidden_verbs_in(subject)
    if forbidden:
        raise ControlCommandOnBusError(
            f"subject {subject!r} names forbidden control verb(s) "
            f"{sorted(forbidden)}; the event bus is advisory/notification-only "
            "and must never carry a control command"
        )
    if not subject.startswith(f"{SUBJECT_ROOT}."):
        raise ControlCommandOnBusError(
            f"subject {subject!r} is outside the advisory namespace "
            f"{SUBJECT_ROOT!r}.*; refusing to use it on the bus"
        )


def event_type_of(subject: str) -> str:
    """Return the short event type (subject with the root namespace stripped)."""
    prefix = f"{SUBJECT_ROOT}."
    return subject[len(prefix):] if subject.startswith(prefix) else subject
