"""The registry of content parsers run inside the resource-capped sandbox.

Each parser takes raw bytes and returns a small JSON-serialisable summary. They
are dispatched *by name* so the sandbox runner only ever receives a trusted
parser key plus an input path — never an arbitrary callable — which keeps the
sandbox boundary tight.

Two special "self-test" parsers (``__sleep__`` / ``__allocate__``) exist purely
so the timeout and memory caps can be proven in CI; they are canaries, never
invoked on real uploads.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from . import csv_safe, xml_safe


def parse_xml(data: bytes) -> dict[str, object]:
    """Safely parse XML (XXE/XSLT/entity-safe) and summarise the root element."""
    root = xml_safe.parse_xml(data)
    return {"parser": "xml", "root_tag": root.tag, "child_count": len(list(root))}


def parse_csv(data: bytes) -> dict[str, object]:
    """Parse CSV text and report rows plus any formula-injection cells found."""
    import csv
    import io

    text = data.decode("utf-8", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    dangerous = sum(1 for row in rows for cell in row if csv_safe.is_dangerous(cell))
    return {"parser": "csv", "rows": len(rows), "dangerous_cells": dangerous}


def _selftest_sleep(data: bytes) -> dict[str, object]:  # pragma: no cover - runs in child
    """Sleep far longer than any sane timeout so the timeout cap can be proven."""
    time.sleep(3600)
    return {"parser": "__sleep__"}


def _selftest_allocate(data: bytes) -> dict[str, object]:  # pragma: no cover - child
    """Allocate memory until the address-space cap kills the process."""
    blocks: list[bytearray] = []
    while True:
        blocks.append(bytearray(64 * 1024 * 1024))
    return {"parser": "__allocate__"}  # unreachable


#: Parser dispatch table used by the sandbox runner.
PARSERS: dict[str, Callable[[bytes], dict[str, object]]] = {
    "xml": parse_xml,
    "csv": parse_csv,
    "__sleep__": _selftest_sleep,
    "__allocate__": _selftest_allocate,
}


def get_parser(name: str) -> Callable[[bytes], dict[str, object]]:
    """Return the parser callable for ``name`` (KeyError if unknown)."""
    return PARSERS[name]
