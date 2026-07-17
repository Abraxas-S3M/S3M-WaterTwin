"""The safety boundary for the WaterTwin.

The twin is an *advisory* system. It never actuates equipment or writes control
setpoints back to the plant/SCADA. This module is the single source of truth for
that guarantee: ``control_write_enabled`` is a hard invariant and is ``False``
until a dedicated, reviewed control-write capability is deliberately introduced
in a later phase.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

CONTROL_MODE = "advisory"

# Hard safety invariant. There is no control-write endpoint in this service and
# nothing may flip this to ``True`` at runtime.
CONTROL_WRITE_ENABLED = False


class ControlBoundary(BaseModel):
    """Describes what the twin is and is not permitted to do to the plant."""

    control_mode: str = Field(default=CONTROL_MODE)
    control_write_enabled: bool = Field(default=CONTROL_WRITE_ENABLED)
    description: str = Field(
        default=(
            "Advisory digital twin. Read-only with respect to plant control: it "
            "may observe telemetry and produce recommendations, but never writes "
            "setpoints or actuates equipment."
        )
    )
    allowed_actions: list[str] = Field(
        default_factory=lambda: ["read_telemetry", "analyze", "recommend"]
    )
    blocked_actions: list[str] = Field(
        default_factory=lambda: [
            "write_setpoint",
            "actuate_equipment",
            "start_stop_asset",
            "override_safety_interlock",
        ]
    )


def current_boundary() -> ControlBoundary:
    """Return the current (immutable) control boundary."""

    return ControlBoundary(
        control_mode=CONTROL_MODE,
        control_write_enabled=CONTROL_WRITE_ENABLED,
    )
