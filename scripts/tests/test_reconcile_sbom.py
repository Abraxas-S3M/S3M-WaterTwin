"""Tests for the SBOM <-> open-source-register reconciliation tool.

Covers:
  * the repository's real SBOMs reconcile clean against the register;
  * a dependency present in an SBOM but absent from the register is flagged;
  * direct dependencies are identified from the SBOM dependency graph.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import reconcile_sbom  # noqa: E402

REGISTER = REPO_ROOT / "docs" / "licensing" / "open-source-register.md"
SBOM_DIR = REPO_ROOT / "docs" / "licensing" / "sbom"


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_repo_sboms_reconcile_clean():
    sboms = sorted(SBOM_DIR.glob("*.cdx.json"))
    assert sboms, "expected generated SBOMs under docs/licensing/sbom/"
    missing = reconcile_sbom.reconcile(sboms, REGISTER)
    for name, flagged in missing.items():
        assert flagged == [], f"{name} has unregistered direct deps: {flagged}"


def test_dep_absent_from_register_is_flagged(tmp_path):
    register = tmp_path / "register.md"
    register.write_text(
        "# Register\n\n| Component | License |\n|---|---|\n| fastapi | MIT |\n",
        encoding="utf-8",
    )
    # No dependency graph / root -> every component is treated as direct.
    sbom = _write(
        tmp_path / "svc.cdx.json",
        {
            "components": [
                {"bom-ref": "fastapi@1", "name": "fastapi", "version": "1"},
                {"bom-ref": "sneaky@2", "name": "totally-unregistered-lib", "version": "2"},
            ]
        },
    )

    missing = reconcile_sbom.reconcile([sbom], register)
    flagged = missing["svc.cdx.json"]
    names = {c["name"] for c in flagged}
    assert names == {"totally-unregistered-lib"}


def test_main_exits_nonzero_when_unregistered(tmp_path, capsys):
    register = tmp_path / "register.md"
    register.write_text("| Component |\n|---|\n| fastapi |\n", encoding="utf-8")
    sbom = _write(
        tmp_path / "svc.cdx.json",
        {"components": [{"bom-ref": "x@2", "name": "unregistered-thing", "version": "2"}]},
    )
    rc = reconcile_sbom.main(["--sbom", str(sbom), "--register", str(register)])
    assert rc == 1
    assert "unregistered-thing" in capsys.readouterr().out


def test_extras_marker_is_normalized(tmp_path):
    # Register lists uvicorn[standard]; SBOM records bare "uvicorn".
    register = tmp_path / "register.md"
    register.write_text("| Component |\n|---|\n| uvicorn[standard] |\n", encoding="utf-8")
    sbom = _write(
        tmp_path / "svc.cdx.json",
        {"components": [{"bom-ref": "u@1", "name": "uvicorn", "version": "1"}]},
    )
    missing = reconcile_sbom.reconcile([sbom], register)
    assert missing["svc.cdx.json"] == []


def test_only_direct_deps_are_checked_when_graph_present(tmp_path):
    # A transitive-only component absent from the register must NOT be flagged;
    # only the root's direct dependencies are reconciled.
    register = tmp_path / "register.md"
    register.write_text("| Component |\n|---|\n| direct-dep |\n", encoding="utf-8")
    sbom = _write(
        tmp_path / "app.cdx.json",
        {
            "metadata": {"component": {"bom-ref": "root@1", "name": "app"}},
            "components": [
                {"bom-ref": "direct@1", "name": "direct-dep", "version": "1"},
                {"bom-ref": "trans@1", "name": "transitive-dep", "version": "1"},
            ],
            "dependencies": [
                {"ref": "root@1", "dependsOn": ["direct@1"]},
                {"ref": "direct@1", "dependsOn": ["trans@1"]},
            ],
        },
    )
    missing = reconcile_sbom.reconcile([sbom], register)
    # transitive-dep is not registered but is not a direct dep -> not flagged.
    assert missing["app.cdx.json"] == []
