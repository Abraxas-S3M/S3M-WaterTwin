"""The read-only, advisory control boundary for the ingest service.

This mirrors the canonical :class:`canonical_water_model.ControlBoundary` and is
the single source of truth the ingest service stamps onto every response, audit
entry and capability descriptor. It is deliberately a frozen constant: there is
no code path in this service that constructs a boundary with
``control_write_enabled=True`` (enforced by the OT-write-forbid guard test).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Advisory control mode — the ingest service never controls anything.
CONTROL_MODE = "advisory"

#: Human approval is always required before any advisory output is acted upon.
OPERATOR_APPROVAL_REQUIRED = True

#: No control-write path exists anywhere in this service.
CONTROL_WRITE_ENABLED = False


@dataclass(frozen=True)
class ControlBoundary:
    """The immutable advisory/read-only control boundary."""

    control_mode: str = CONTROL_MODE
    operator_approval_required: bool = OPERATOR_APPROVAL_REQUIRED
    control_write_enabled: bool = CONTROL_WRITE_ENABLED

    def as_dict(self) -> dict[str, object]:
        return {
            "control_mode": self.control_mode,
            "operator_approval_required": self.operator_approval_required,
            "control_write_enabled": self.control_write_enabled,
        }


#: The one boundary value the service ever emits.
CONTROL_BOUNDARY = ControlBoundary()


def safety_invariant_intact() -> bool:
    """True iff the advisory/read-only safety invariant still holds.

    The invariant is fixed and independent of any tenant, plan, quota or
    deployment profile: advisory mode, approval required, no control write.
    """
    return (
        CONTROL_BOUNDARY.control_mode == "advisory"
        and CONTROL_BOUNDARY.operator_approval_required is True
        and CONTROL_BOUNDARY.control_write_enabled is False
    )
