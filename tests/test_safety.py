"""Tests for the advisory-only safety boundary."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from watertwin.safety import (
    CONTROL_MODE,
    CONTROL_WRITE_ENABLED,
    OPERATOR_APPROVAL_REQUIRED,
    ControlWriteAttemptError,
    SafetyEnvelope,
    assert_advisory_only,
    default_safety_envelope,
)


def test_module_constants_hold_the_boundary() -> None:
    assert CONTROL_MODE == "advisory"
    assert OPERATOR_APPROVAL_REQUIRED is True
    assert CONTROL_WRITE_ENABLED is False


def test_default_envelope_is_advisory() -> None:
    envelope = default_safety_envelope()
    assert envelope.control_mode == "advisory"
    assert envelope.operator_approval_required is True
    assert envelope.control_write_enabled is False


def test_envelope_is_frozen() -> None:
    envelope = default_safety_envelope()
    with pytest.raises(ValidationError):
        envelope.control_write_enabled = True  # type: ignore[misc]


def test_cannot_enable_control_write() -> None:
    with pytest.raises(ValidationError):
        SafetyEnvelope(control_write_enabled=True)  # type: ignore[arg-type]


def test_cannot_leave_advisory_mode() -> None:
    with pytest.raises(ValidationError):
        SafetyEnvelope(control_mode="autonomous")  # type: ignore[arg-type]


def test_cannot_disable_operator_approval() -> None:
    with pytest.raises(ValidationError):
        SafetyEnvelope(operator_approval_required=False)  # type: ignore[arg-type]


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        SafetyEnvelope(command_plc=True)  # type: ignore[call-arg]


def test_assert_advisory_only_returns_envelope() -> None:
    envelope = assert_advisory_only()
    assert isinstance(envelope, SafetyEnvelope)


def test_assert_advisory_only_rejects_tampered_envelope() -> None:
    envelope = default_safety_envelope()
    object.__setattr__(envelope, "control_write_enabled", True)
    with pytest.raises(ControlWriteAttemptError):
        assert_advisory_only(envelope)
