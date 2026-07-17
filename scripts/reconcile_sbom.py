#!/usr/bin/env python3
"""Reconcile CycloneDX SBOMs against the open-source register.

Every *direct* dependency recorded in a generated SBOM under
``docs/licensing/sbom/`` must also appear in
``docs/licensing/open-source-register.md``. This tool re-walks each SBOM,
extracts its direct dependencies, and flags any that are missing from the
register so the register can never silently drift behind the pinned
dependencies.

"Direct" dependencies are identified from the SBOM dependency graph: the
components the root component (the app/service itself) directly depends on. SBOMs
produced by ``cyclonedx-py requirements`` have no root component — every listed
component is a pinned direct dependency — so in that case all components are
treated as direct.

Usage:
    python scripts/reconcile_sbom.py                # reconcile the repo SBOMs
    python scripts/reconcile_sbom.py --sbom a.json --register reg.md

Exit code is non-zero when any direct dependency is missing from the register,
so the CI supply-chain job can gate on it.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTER = REPO_ROOT / "docs" / "licensing" / "open-source-register.md"
DEFAULT_SBOM_DIR = REPO_ROOT / "docs" / "licensing" / "sbom"


def normalize(name: str) -> str:
    """Normalize a component/package name for comparison.

    Lowercases, trims, strips surrounding backticks, and drops extras markers
    such as ``uvicorn[standard]`` -> ``uvicorn`` so the register may list the
    installed extra while the SBOM records the bare distribution name.
    """
    name = name.strip().strip("`").strip()
    name = re.sub(r"\[.*?\]", "", name)  # drop [extras]
    return name.strip().lower()


def parse_register(register_path: Path) -> set[str]:
    """Collect the set of registered component names from the register markdown.

    Every first (left-most) cell of every markdown table row is treated as a
    registered component name. Header and separator rows are harmless extra
    entries.
    """
    registered: set[str] = set()
    for line in register_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        if not first or set(first) <= set("-: "):  # separator row
            continue
        registered.add(normalize(first))
    return registered


def _component_name(component: dict[str, Any]) -> str:
    group = component.get("group")
    name = component.get("name", "")
    return f"{group}/{name}" if group else name


def sbom_direct_components(sbom: dict[str, Any]) -> list[dict[str, str]]:
    """Return the SBOM's direct dependencies as ``{name, version, license}``."""
    components = sbom.get("components", []) or []
    by_ref = {c.get("bom-ref"): c for c in components if c.get("bom-ref")}

    root_ref = (sbom.get("metadata", {}) or {}).get("component", {}).get("bom-ref")
    direct: list[dict[str, Any]] = []
    if root_ref:
        depends_on: list[str] = []
        for dep in sbom.get("dependencies", []) or []:
            if dep.get("ref") == root_ref:
                depends_on = dep.get("dependsOn", []) or []
                break
        for ref in depends_on:
            comp = by_ref.get(ref)
            if comp is not None:
                direct.append(comp)
    else:
        # cyclonedx-py requirements output: every component is a direct pin.
        direct = list(components)

    out: list[dict[str, str]] = []
    for comp in direct:
        licenses = comp.get("licenses", []) or []
        license_id = ""
        if licenses:
            lic = licenses[0].get("license", {}) or {}
            license_id = lic.get("id") or lic.get("name") or ""
        out.append(
            {
                "name": _component_name(comp),
                "version": comp.get("version", ""),
                "license": license_id,
            }
        )
    return out


def reconcile(sbom_paths: list[Path], register_path: Path) -> dict[str, list[dict[str, str]]]:
    """Return, per SBOM, the direct dependencies missing from the register."""
    registered = parse_register(register_path)
    missing: dict[str, list[dict[str, str]]] = {}
    for sbom_path in sbom_paths:
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
        flagged = [
            comp
            for comp in sbom_direct_components(sbom)
            if normalize(comp["name"]) not in registered
        ]
        missing[sbom_path.name] = flagged
    return missing


def _discover_sboms(sbom_dir: Path) -> list[Path]:
    return sorted(sbom_dir.glob("*.cdx.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sbom",
        action="append",
        default=None,
        help="Path to an SBOM file (repeatable). Defaults to docs/licensing/sbom/*.cdx.json",
    )
    parser.add_argument(
        "--register",
        default=str(DEFAULT_REGISTER),
        help="Path to the open-source register markdown.",
    )
    args = parser.parse_args(argv)

    register_path = Path(args.register)
    sbom_paths = [Path(p) for p in args.sbom] if args.sbom else _discover_sboms(DEFAULT_SBOM_DIR)

    if not sbom_paths:
        print(f"::error::no SBOM files found (looked in {DEFAULT_SBOM_DIR})")
        return 2

    missing = reconcile(sbom_paths, register_path)
    total_missing = sum(len(v) for v in missing.values())

    for sbom_name, flagged in missing.items():
        if flagged:
            print(f"::error::{sbom_name}: {len(flagged)} direct dependency(ies) missing "
                  f"from {register_path.name}:")
            for comp in flagged:
                print(f"    - {comp['name']} {comp['version']} ({comp['license'] or 'unknown'})")
        else:
            print(f"OK: {sbom_name}: all direct dependencies are registered.")

    if total_missing:
        print(f"::error::reconcile failed: {total_missing} unregistered direct dependency(ies). "
              f"Add them to {register_path}.")
        return 1
    print("OK: every SBOM direct dependency is reconciled against the register.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
