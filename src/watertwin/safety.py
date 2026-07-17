"""Safety boundary for S3M-WaterTwin.

This module encodes the platform's non-negotiable safety boundary as immutable
constants and a validated, frozen :class:`SafetyEnvelope`. The invariants are:

* ``control_mode == "advisory"``
* ``operator_approval_required is True``
* ``control_write_enabled is False``

The envelope is *fail-closed*: it is impossible to construct a
:class:`SafetyEnvelope` that violates these invariants. Any attempt raises a
``ValidationError``. This gives the rest of the codebase (and the test suite) a
single, authoritative object to assert against.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

#: The only permitted control mode. The platform is advisory-only.
CONTROL_MODE: Literal["advisory"] = "advisory"

#: A human operator must approve any recommendation before it is acted upon.
OPERATOR_APPROVAL_REQUIRED: bool = True

#: There is no control-write code path. This flag can never be True.
CONTROL_WRITE_ENABLED: bool = False


class ControlWriteAttemptError(RuntimeError):
    """Raised if any code path attempts to enable or perform a control write.

    The platform never commands a PLC, SCADA, VFD, valve, pump, or dosing
    system. Reaching this error indicates a programming mistake that would
    breach the advisory-only safety boundary.
    """


class SafetyEnvelope(BaseModel):
    """Immutable, self-validating statement of the advisory safety boundary.

    Instances are frozen and can only ever describe an advisory, approval-gated,
    read-only posture. Construction with any other values fails.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    control_mode: Literal["advisory"] = CONTROL_MODE
    operator_approval_required: Literal[True] = OPERATOR_APPROVAL_REQUIRED
    control_write_enabled: Literal[False] = CONTROL_WRITE_ENABLED

    @field_validator("control_write_enabled")
    @classmethod
    def _forbid_control_write(cls, value: bool) -> bool:
        if value is not False:
            raise ControlWriteAttemptError(
                "control_write_enabled must be False: there is no control-write "
                "code path in S3M-WaterTwin."
            )
        return value


def default_safety_envelope() -> SafetyEnvelope:
    """Return the canonical advisory-only :class:`SafetyEnvelope`."""

    return SafetyEnvelope()


def assert_advisory_only(envelope: SafetyEnvelope | None = None) -> SafetyEnvelope:
    """Assert the advisory-only safety boundary holds and return the envelope.

    Args:
        envelope: An envelope to check. If ``None``, the canonical default is
            used.

    Returns:
        The validated :class:`SafetyEnvelope`.

    Raises:
        ControlWriteAttemptError: If the boundary is violated in any way.
    """

    envelope = envelope or default_safety_envelope()
    if envelope.control_mode != "advisory":
        raise ControlWriteAttemptError(
            f"control_mode must be 'advisory', got {envelope.control_mode!r}."
        )
    if envelope.operator_approval_required is not True:
        raise ControlWriteAttemptError("operator_approval_required must be True.")
    if envelope.control_write_enabled is not False:
        raise ControlWriteAttemptError("control_write_enabled must be False.")
    return envelope
