"""Tests for the npm audit CI gate (severity threshold + ignore allowlist)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import npm_audit_gate  # noqa: E402


def _audit(severity: str, ghsa: str = "GHSA-aaaa-bbbb-cccc") -> dict:
    return {
        "vulnerabilities": {
            "some-pkg": {
                "severity": severity,
                "via": [
                    {
                        "severity": severity,
                        "title": "example advisory",
                        "url": f"https://github.com/advisories/{ghsa}",
                        "source": 12345,
                    }
                ],
            }
        }
    }


def test_high_severity_is_a_finding():
    findings = npm_audit_gate.evaluate(_audit("high"), set(), "high")
    assert len(findings) == 1
    assert findings[0]["package"] == "some-pkg"


def test_below_threshold_is_ignored():
    assert npm_audit_gate.evaluate(_audit("moderate"), set(), "high") == []


def test_allowlisted_ghsa_is_excluded():
    ignores = {"ghsa-aaaa-bbbb-cccc"}
    assert npm_audit_gate.evaluate(_audit("critical"), ignores, "high") == []


def test_allowlisted_url_is_excluded():
    ignores = {"https://github.com/advisories/ghsa-aaaa-bbbb-cccc"}
    assert npm_audit_gate.evaluate(_audit("high"), ignores, "high") == []


def test_no_vulnerabilities_is_clean():
    assert npm_audit_gate.evaluate({"vulnerabilities": {}}, set(), "high") == []


def test_load_ignores_skips_comments(tmp_path):
    f = tmp_path / "ig.txt"
    f.write_text("# comment\n\nGHSA-1111-2222-3333\n", encoding="utf-8")
    assert npm_audit_gate.load_ignores(f) == {"ghsa-1111-2222-3333"}


def test_main_fails_on_high(tmp_path, monkeypatch, capsys):
    import io
    import json as _json

    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(_audit("critical"))))
    rc = npm_audit_gate.main(
        ["--ignore-file", str(tmp_path / "none.txt"), "--min-severity", "high"]
    )
    assert rc == 1
    assert "vulnerability" in capsys.readouterr().out
