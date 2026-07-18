"""Sandboxed parse worker.

A customer upload is untrusted input, so it is never parsed in the API process.
Instead :func:`run_parse_job` runs the parser in a **separate, hardened child
process** and returns a :class:`~app.parsers.base.ParseResult`. The child:

* runs as a **non-root** process (it drops privileges if started as root, and
  refuses to run as root unless explicitly allowed by config);
* has **no network egress** — socket creation is blocked, so an attempt to dial
  out fails (asserted by the test-suite);
* runs with a **read-only** view of the filesystem except a single scratch
  directory it ``chdir``s into (the container mounts the root filesystem
  read-only; the worker additionally caps how much it may write via
  ``RLIMIT_FSIZE``);
* is bounded by a **wall-clock timeout** and a **memory cap**, both config-driven.

A crash, an out-of-memory kill, or a timeout is turned into a clean
``status = parse_failed`` :class:`ParseResult` with a useful message — it never
propagates an exception into, or takes down, the API process.
"""

from __future__ import annotations

import contextlib
import multiprocessing
import os
import resource
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .parsers import ParseResult, ParseScope, ParseStatus

_PARSE_FAILED_PARSER = "sandbox-worker"


class NoNetworkError(RuntimeError):
    """Raised inside the sandbox when code attempts to create a socket."""


def install_no_network() -> None:
    """Disable network egress in the current process by blocking sockets.

    Replaces the socket constructors with a stub that raises
    :class:`NoNetworkError`. Existing file-descriptor based IPC (the result pipe)
    is unaffected because it does not construct new sockets.
    """

    def _blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise NoNetworkError("network egress is disabled in the ingest sandbox")

    socket.socket = _blocked  # type: ignore[assignment,misc]
    socket.create_connection = _blocked  # type: ignore[assignment]
    if hasattr(socket, "create_server"):
        socket.create_server = _blocked  # type: ignore[assignment]


@dataclass(frozen=True)
class SandboxPolicy:
    """The hardening envelope applied to the child process (config-driven)."""

    memory_mb: int
    scratch_dir: str
    max_fsize_bytes: int
    timeout_s: float
    allow_network: bool = False
    allow_root: bool = False


@dataclass(frozen=True)
class SandboxOutcome:
    """The result of a sandboxed run: either a payload or a failure reason."""

    ok: bool
    kind: str  # "ok" | "timeout" | "crash" | "error"
    error: str | None = None
    payload: Any = None


def _apply_policy(policy: SandboxPolicy) -> None:
    """Harden the current (child) process according to ``policy``.

    Order matters: drop privileges, confine the filesystem, cap resources, then
    cut the network last so the earlier steps can still touch what they need.
    """
    _drop_privileges(policy.allow_root)
    _confine_filesystem(policy)
    _cap_resources(policy)
    if not policy.allow_network:
        install_no_network()


def _drop_privileges(allow_root: bool) -> None:
    if os.geteuid() != 0:
        return
    try:
        import grp
        import pwd

        nobody = pwd.getpwnam("nobody")
        try:
            nogroup = grp.getgrnam("nogroup").gr_gid
        except KeyError:
            nogroup = nobody.pw_gid
        os.setgroups([])
        os.setgid(nogroup)
        os.setuid(nobody.pw_uid)
    except Exception as exc:
        if not allow_root:
            raise RuntimeError(
                "sandbox worker refuses to run as root and could not drop "
                f"privileges: {exc}"
            ) from exc
    if os.geteuid() == 0 and not allow_root:
        raise RuntimeError("sandbox worker refuses to run as root")


def _confine_filesystem(policy: SandboxPolicy) -> None:
    os.makedirs(policy.scratch_dir, exist_ok=True)
    os.chdir(policy.scratch_dir)
    os.environ["TMPDIR"] = policy.scratch_dir


def _cap_resources(policy: SandboxPolicy) -> None:
    fsize = policy.max_fsize_bytes
    _set_limit(resource.RLIMIT_FSIZE, fsize)
    cpu_seconds = int(policy.timeout_s) + 2
    _set_limit(resource.RLIMIT_CPU, cpu_seconds)
    if policy.memory_mb > 0:
        as_bytes = _memory_limit_bytes(policy.memory_mb)
        if as_bytes is not None:
            _set_limit(resource.RLIMIT_AS, as_bytes)


def _memory_limit_bytes(memory_mb: int) -> int | None:
    """Resolve an absolute ``RLIMIT_AS`` that caps *additional* memory.

    ``RLIMIT_AS`` is an absolute virtual-address-space ceiling, but a forked
    interpreter already maps a large virtual footprint. We therefore set the cap
    to the current footprint plus the configured allowance, so the worker cannot
    grow beyond the allowance while still being able to start.
    """
    requested = memory_mb * 1024 * 1024
    current = _current_address_space()
    if current is None:
        return requested
    return current + requested


def _current_address_space() -> int | None:
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            pages = int(handle.read().split()[0])
        return pages * resource.getpagesize()
    except Exception:
        return None


def _set_limit(which: int, value: int) -> None:
    try:
        soft, hard = resource.getrlimit(which)
        new_hard = value if hard == resource.RLIM_INFINITY else min(value, hard)
        resource.setrlimit(which, (min(value, new_hard), new_hard))
    except (ValueError, OSError):
        # Best-effort: a platform that refuses a limit must not break the worker.
        pass


def _child_main(
    conn: Any, target: Callable[..., Any], args: tuple[Any, ...], policy: SandboxPolicy
) -> None:  # pragma: no cover - runs only in the forked child
    try:
        _apply_policy(policy)
    except BaseException as exc:
        _safe_send(conn, ("error", f"sandbox hardening failed: {exc}"))
        os._exit(0)
    try:
        result = target(*args)
        _safe_send(conn, ("ok", result))
    except BaseException as exc:
        _safe_send(conn, ("error", f"{type(exc).__name__}: {exc}"))
    finally:
        with contextlib.suppress(Exception):
            conn.close()
        os._exit(0)


def _safe_send(conn: Any, message: tuple[str, Any]) -> None:  # pragma: no cover - child only
    with contextlib.suppress(Exception):
        conn.send(message)


def _terminate(proc: multiprocessing.process.BaseProcess) -> None:
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=2.0)
    if proc.is_alive():  # pragma: no cover - defensive escalation
        proc.kill()
        proc.join(timeout=2.0)


def run_in_sandbox(
    target: Callable[..., Any], args: tuple[Any, ...], policy: SandboxPolicy
) -> SandboxOutcome:
    """Run ``target(*args)`` in a hardened child process and return its outcome.

    The target and its result are exchanged over an OS pipe. A run that exceeds
    ``policy.timeout_s`` is terminated and reported as a timeout; a child that
    dies without sending a result is reported as a crash. This function never
    raises on a worker failure.
    """
    os.makedirs(policy.scratch_dir, exist_ok=True)
    ctx = multiprocessing.get_context("fork")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child_main, args=(child_conn, target, args, policy))
    proc.start()
    child_conn.close()

    if not parent_conn.poll(policy.timeout_s):
        _terminate(proc)
        parent_conn.close()
        return SandboxOutcome(
            ok=False,
            kind="timeout",
            error=f"parse exceeded the {policy.timeout_s:.1f}s wall-clock timeout",
        )

    try:
        kind, data = parent_conn.recv()
    except EOFError:
        proc.join(timeout=1.0)
        return SandboxOutcome(
            ok=False,
            kind="crash",
            error=(
                "sandbox worker exited without a result "
                f"(exit code {proc.exitcode}); the input may have exhausted the "
                "memory cap or otherwise crashed the worker"
            ),
        )
    finally:
        parent_conn.close()

    proc.join(timeout=5.0)
    if kind == "ok":
        return SandboxOutcome(ok=True, kind="ok", payload=data)
    return SandboxOutcome(ok=False, kind="error", error=str(data))


def _parse_target(path: str, file_format: str, sections: list[str]) -> dict[str, Any]:
    """Top-level parse entrypoint run inside the sandbox (returns a JSON dict).

    Kept module-level (and free of shared state) so it is safe to run in the
    isolated worker. Reads the file, refuses XML external-entity attacks, and
    delegates to the confirmed parser.
    """
    from .parsers import get_parser, guard_unsafe_content

    with open(path, "rb") as handle:
        raw = handle.read()
    guard_unsafe_content(raw)
    parser = get_parser(file_format)
    scope = ParseScope(file_format=file_format, sections=list(sections))
    return parser.parse(path, scope).model_dump(mode="json")


def run_parse_job(
    path: str,
    scope: ParseScope,
    *,
    timeout_s: float,
    memory_mb: int,
    scratch_dir: str,
    max_fsize_bytes: int,
    allow_root: bool = False,
) -> ParseResult:
    """Parse ``path`` in the sandbox and return a :class:`ParseResult`.

    A crashed, timed-out, or otherwise failed worker yields a ``parse_failed``
    result carrying a useful message — never a raised exception.
    """
    policy = SandboxPolicy(
        memory_mb=memory_mb,
        scratch_dir=scratch_dir,
        max_fsize_bytes=max_fsize_bytes,
        timeout_s=timeout_s,
        allow_network=False,
        allow_root=allow_root,
    )
    outcome = run_in_sandbox(_parse_target, (path, scope.file_format, scope.sections), policy)
    if outcome.ok:
        return ParseResult.model_validate(outcome.payload)
    return ParseResult(
        status=ParseStatus.parse_failed,
        parser=_PARSE_FAILED_PARSER,
        error=outcome.error or "parse failed",
    )
