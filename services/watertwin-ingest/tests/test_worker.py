"""Tests for the sandboxed parse worker (isolation, timeout, crash handling)."""

from __future__ import annotations

import os
import socket
import time

from app import worker
from app.parsers.base import ParseScope, ParseStatus
from app.worker import SandboxPolicy, run_in_sandbox, run_parse_job

from .conftest import DEMO_INP

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _policy(scratch, *, timeout_s=5.0, memory_mb=512):
    return SandboxPolicy(
        memory_mb=memory_mb,
        scratch_dir=str(scratch),
        max_fsize_bytes=64 * 1024 * 1024,
        timeout_s=timeout_s,
    )


# --- top-level targets (run inside the forked sandbox child) ----------------


def _open_socket() -> str:
    socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    return "socket created"


def _return_value() -> int:
    return 42


def _sleep_forever() -> int:
    time.sleep(30)
    return 1


def _euid() -> int:
    return os.geteuid()


def _hard_exit() -> int:  # pragma: no cover - child dies before returning a result
    os._exit(1)
    return 0


def _slow_parse_target(path: str, file_format: str, sections: list[str]) -> dict:
    time.sleep(30)
    return {}


# --- tests -----------------------------------------------------------------


def test_worker_has_no_network_egress(tmp_path):
    outcome = run_in_sandbox(_open_socket, (), _policy(tmp_path))
    assert outcome.ok is False
    assert "NoNetworkError" in (outcome.error or "")


def test_install_no_network_blocks_socket_creation():
    # Guard the real socket module in a throwaway subprocess-like context by
    # exercising the installer directly, then restoring it.
    original = socket.socket
    try:
        worker.install_no_network()
        raised = False
        try:
            socket.socket()
        except worker.NoNetworkError:
            raised = True
        assert raised
    finally:
        socket.socket = original


def test_timeout_is_reported_and_process_survives(tmp_path):
    started = time.monotonic()
    outcome = run_in_sandbox(_sleep_forever, (), _policy(tmp_path, timeout_s=0.5))
    elapsed = time.monotonic() - started
    assert outcome.ok is False
    assert outcome.kind == "timeout"
    assert elapsed < 5.0
    # The calling (API) process is unaffected: a normal job runs right after.
    healthy = run_in_sandbox(_return_value, (), _policy(tmp_path))
    assert healthy.ok is True and healthy.payload == 42


def test_crashed_worker_is_reported_not_raised(tmp_path):
    outcome = run_in_sandbox(_hard_exit, (), _policy(tmp_path))
    assert outcome.ok is False
    assert outcome.kind == "crash"


def test_worker_runs_non_root(tmp_path):
    outcome = run_in_sandbox(_euid, (), _policy(tmp_path))
    assert outcome.ok is True
    assert outcome.payload != 0


def test_run_parse_job_on_demo_returns_parsed(tmp_path):
    result = run_parse_job(
        DEMO_INP,
        ParseScope(file_format="epanet"),
        timeout_s=30,
        memory_mb=512,
        scratch_dir=str(tmp_path),
        max_fsize_bytes=64 * 1024 * 1024,
    )
    assert result.status is ParseStatus.parsed
    assert result.entity_counts()["junction"] == 6


def test_run_parse_job_timeout_yields_parse_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "_parse_target", _slow_parse_target)
    result = run_parse_job(
        DEMO_INP,
        ParseScope(file_format="epanet"),
        timeout_s=0.5,
        memory_mb=512,
        scratch_dir=str(tmp_path),
        max_fsize_bytes=64 * 1024 * 1024,
    )
    assert result.status is ParseStatus.parse_failed
    assert "timeout" in (result.error or "")


def test_run_parse_job_rejects_xxe(tmp_path):
    result = run_parse_job(
        os.path.join(FIXTURES, "xxe.inp"),
        ParseScope(file_format="epanet"),
        timeout_s=30,
        memory_mb=512,
        scratch_dir=str(tmp_path),
        max_fsize_bytes=64 * 1024 * 1024,
    )
    assert result.status is ParseStatus.parse_failed
    assert "UnsafeContentError" in (result.error or "")
