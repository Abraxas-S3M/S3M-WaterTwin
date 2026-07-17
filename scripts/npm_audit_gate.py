#!/usr/bin/env python3
"""Gate on `npm audit --json` output, honouring a documented ignore file.

The CI `vuln-scan` job pipes `npm audit --json` into this script. It fails
(exit code 1) when any vulnerability at or above ``--min-severity`` remains
after removing advisories listed in the ignore file
(``security/npm-audit-ignore.txt``). Accepted advisories are matched by GHSA id,
numeric source id, or advisory URL.

Usage:
    npm audit --json | python scripts/npm_audit_gate.py \
        --ignore-file security/npm-audit-ignore.txt --min-severity high
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SEVERITY_ORDER = {"info": 0, "low": 1, "moderate": 2, "high": 3, "critical": 4}


def load_ignores(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ignores: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        ignores.add(line.lower())
    return ignores


def _advisory_tokens(via: dict) -> set[str]:
    """Identifiers we can match an ignore entry against for a single advisory."""
    tokens: set[str] = set()
    for key in ("url", "source", "name", "title"):
        val = via.get(key)
        if val is not None:
            tokens.add(str(val).lower())
    url = via.get("url", "")
    if isinstance(url, str) and "GHSA-" in url:
        tokens.add(url.rstrip("/").split("/")[-1].lower())
    return tokens


def evaluate(audit: dict, ignores: set[str], min_severity: str) -> list[dict]:
    """Return the list of non-ignored findings at/above ``min_severity``."""
    threshold = SEVERITY_ORDER[min_severity]
    findings: list[dict] = []
    vulns = audit.get("vulnerabilities", {}) or {}
    for pkg, info in vulns.items():
        severity = (info.get("severity") or "info").lower()
        if SEVERITY_ORDER.get(severity, 0) < threshold:
            continue
        # Collect the concrete advisories behind this package entry.
        advisories = [v for v in (info.get("via") or []) if isinstance(v, dict)]
        if not advisories:
            # A package flagged only transitively; treat as one finding.
            findings.append({"package": pkg, "severity": severity, "id": None})
            continue
        for adv in advisories:
            tokens = _advisory_tokens(adv)
            if tokens & ignores:
                continue
            findings.append(
                {
                    "package": pkg,
                    "severity": (adv.get("severity") or severity).lower(),
                    "id": adv.get("url") or adv.get("source"),
                    "title": adv.get("title"),
                }
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ignore-file", default="security/npm-audit-ignore.txt")
    parser.add_argument("--min-severity", default="high", choices=list(SEVERITY_ORDER))
    parser.add_argument(
        "--input",
        default="-",
        help="Path to npm audit --json output, or '-' for stdin (default).",
    )
    args = parser.parse_args(argv)

    raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    if not raw.strip():
        print("OK: npm audit produced no output (no vulnerabilities).")
        return 0
    try:
        audit = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"::error::could not parse npm audit JSON: {exc}")
        return 2

    ignores = load_ignores(Path(args.ignore_file))
    findings = evaluate(audit, ignores, args.min_severity)

    if findings:
        print(
            f"::error::npm audit found {len(findings)} vulnerability(ies) at or above "
            f"'{args.min_severity}' (excluding {len(ignores)} accepted advisory(ies)):"
        )
        for f in findings:
            print(f"    - [{f['severity']}] {f['package']}: {f.get('title') or f.get('id')}")
        return 1

    print(
        f"OK: no npm vulnerabilities at or above '{args.min_severity}' "
        f"(accepted advisories: {len(ignores)})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
