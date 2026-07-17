"""S3M-WaterTwin.

A read-only, advisory digital twin for a single seawater reverse-osmosis (RO)
treatment train.

Architecture principle: *S3M is the conductor, not the physics engine.*
Deterministic engineering math lives here, in WaterTwin. S3M-Core orchestrates,
reasons, and explains via structured packets and must never be asked to invent
an engineering value that a calculation should produce.

Safety boundary (asserted throughout the package and its tests):

* ``control_mode = "advisory"``
* ``operator_approval_required = true``
* ``control_write_enabled = false``

There is no control-write code path anywhere in this package. Nothing here may
command a PLC, SCADA, VFD, valve, pump, or dosing system. The platform
recommends; a human decides; everything is audited.
"""

from __future__ import annotations

from watertwin.safety import (
    CONTROL_MODE,
    CONTROL_WRITE_ENABLED,
    OPERATOR_APPROVAL_REQUIRED,
    SafetyEnvelope,
    assert_advisory_only,
    default_safety_envelope,
)

__version__ = "0.1.0"

__all__ = [
    "CONTROL_MODE",
    "CONTROL_WRITE_ENABLED",
    "OPERATOR_APPROVAL_REQUIRED",
    "SafetyEnvelope",
    "__version__",
    "assert_advisory_only",
    "default_safety_envelope",
]
