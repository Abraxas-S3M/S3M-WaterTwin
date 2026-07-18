"""Sandbox child entrypoint: run one named parser on one input file.

This module is executed as a *fresh* Python interpreter by
:func:`app.limits.run_sandboxed` (``python -m app.sandbox_runner <parser> <path>``)
with hard resource limits (address space, CPU) already applied to the child by
the parent's ``preexec_fn`` before ``exec``. Running in a clean child means a
parser DoS (runaway CPU or memory) is contained to — and killed inside — the
child, never the ingest service itself.

It reads the input file, dispatches to the named parser, and writes a JSON
result to stdout. Any failure exits non-zero with a diagnostic on stderr so the
parent can classify it (timeout / memory / error).
"""

from __future__ import annotations

import json
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: sandbox_runner <parser-name> <input-path>", file=sys.stderr)
        return 2
    parser_name, input_path = argv[1], argv[2]

    # Import lazily so the child stays small (no FastAPI/uvicorn in the sandbox).
    from app.parsers import get_parser

    try:
        parser = get_parser(parser_name)
    except KeyError:
        print(f"unknown parser: {parser_name!r}", file=sys.stderr)
        return 2

    with open(input_path, "rb") as fh:
        data = fh.read()

    result = parser(data)
    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main(sys.argv))
