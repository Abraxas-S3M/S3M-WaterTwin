"""Parser sandbox: enforce a wall-clock timeout and a hard memory cap.

A parse job runs in a *fresh child interpreter* (``python -m app.sandbox_runner``)
whose address-space (and CPU) limits are set with :func:`resource.setrlimit` in a
``preexec_fn`` before ``exec``. The parent enforces the wall-clock timeout with
``Popen.communicate(timeout=...)`` and kills the child (and its process group) if
it overruns. This gives two independent, OS-enforced guarantees:

* **Memory cap** — an allocation past the cap raises ``MemoryError`` in the child
  (or the kernel refuses the mapping), so a memory-bomb parser cannot exhaust the
  host. Surfaced as :class:`ParseMemoryExceeded`.
* **Timeout** — a runaway/CPU-bound parser is killed at the deadline. Surfaced as
  :class:`ParseTimeout`.

The sandbox is POSIX-only (it relies on ``resource`` + process groups), which
matches the Linux runtime and CI. Nothing here is a control path.
"""

from __future__ import annotations

import json
import os
import resource
import signal
import subprocess
import sys
import tempfile

from . import config

_SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(os.path.dirname(_SERVICE_ROOT))
_PACKAGES = os.path.join(_REPO_ROOT, "packages")


class ParseSandboxError(Exception):
    """Base class for a parse job that failed inside the sandbox."""


class ParseTimeout(ParseSandboxError):
    """Raised when a parse job exceeds its wall-clock timeout."""


class ParseMemoryExceeded(ParseSandboxError):
    """Raised when a parse job exceeds its memory cap."""


def _limits_preexec(memory_bytes: int, cpu_seconds: int):
    """Return a ``preexec_fn`` that caps the child's address space + CPU.

    Runs in the forked child immediately before ``exec`` so the limits apply to
    the fresh interpreter, not the parent.
    """

    def _apply() -> None:  # pragma: no cover - runs in the forked child
        os.setsid()  # own process group so we can kill the whole tree
        if memory_bytes > 0:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        if cpu_seconds > 0:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))

    return _apply


def run_sandboxed(
    parser_name: str,
    data: bytes,
    *,
    timeout_s: float | None = None,
    memory_bytes: int | None = None,
) -> dict[str, object]:
    """Run ``parser_name`` on ``data`` in a resource-capped child interpreter.

    Returns the parser's JSON result on success. Raises :class:`ParseTimeout`
    when the wall-clock deadline is hit and :class:`ParseMemoryExceeded` when the
    memory cap is breached; any other non-zero exit becomes a
    :class:`ParseSandboxError`.
    """
    timeout_s = config.PARSE_TIMEOUT_SECONDS if timeout_s is None else timeout_s
    memory_bytes = (
        config.PARSE_MEMORY_LIMIT_BYTES if memory_bytes is None else memory_bytes
    )
    # A CPU cap slightly above the wall-clock deadline is a backstop for a busy
    # loop that ignores wall time (belt and suspenders with the timeout below).
    cpu_seconds = max(1, int(timeout_s) + 2)

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([_PACKAGES, _SERVICE_ROOT])

    tmp = tempfile.NamedTemporaryFile(
        prefix="ingest-parse-", suffix=".bin", delete=False
    )
    try:
        tmp.write(data)
        tmp.close()
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.sandbox_runner", parser_name, tmp.name],
            cwd=_SERVICE_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=_limits_preexec(memory_bytes, cpu_seconds),
        )
        try:
            out, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            _kill_group(proc)
            proc.communicate()
            raise ParseTimeout(
                f"parse job exceeded {timeout_s}s timeout"
            ) from exc

        if proc.returncode == 0:
            return json.loads(out.decode("utf-8"))

        stderr_text = err.decode("utf-8", errors="replace")
        # RLIMIT_AS breach: Python raises MemoryError; the kernel may also send
        # SIGKILL (-9) or SIGSEGV if a mapping is refused mid-flight.
        if (
            "MemoryError" in stderr_text
            or proc.returncode in (-signal.SIGKILL, -signal.SIGSEGV)
            or "Cannot allocate memory" in stderr_text
        ):
            raise ParseMemoryExceeded(
                f"parse job exceeded memory cap of {memory_bytes} bytes"
            )
        if proc.returncode == -signal.SIGXCPU:
            raise ParseTimeout(f"parse job exceeded CPU cap of {cpu_seconds}s")
        raise ParseSandboxError(
            f"parse job failed (exit {proc.returncode}): {stderr_text.strip()}"
        )
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill the child's whole process group (best-effort)."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
