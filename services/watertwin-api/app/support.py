"""In-app support bundle generation.

Commercial-hardening work package: **support hooks**. An administrator can
generate a support bundle — a single downloadable ZIP that packages what a
support engineer needs to triage an issue:

* recent application logs (from the in-memory ring buffer),
* the Software Bill of Materials (SBOMs) shipped in ``docs/licensing/sbom``,
* a configuration snapshot (selected environment variables), and
* health / entitlement / audit-tail snapshots.

**Secrets are redacted.** The bundle must never carry credentials. Redaction is
defence-in-depth:

1. Environment variables whose *name* looks like a secret (``*_TOKEN``,
   ``*_SECRET``, ``*PASSWORD*``, …) have their value replaced with a redaction
   marker.
2. Credentials embedded in *values* (e.g. the password in a
   ``postgresql://user:pass@host`` URL) are stripped.
3. Every secret value discovered above is additionally scrubbed as a literal
   from all free-text content (logs, audit payloads), so a secret that leaked
   into a log line is removed too.

The support-bundle tests assert that no seeded secret appears anywhere in the
generated archive.
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime

REDACTED = "***REDACTED***"

# Environment variable *name* tokens that indicate a secret value.
_SECRET_TOKENS = {
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "credentials",
    "authorization",
    "bearer",
    "dsn",
    "apikey",
    "jwks",
}
# A bare "key"/"cert" token is only secret when qualified as a private one.
_PRIVATE_KEY_QUALIFIERS = {"private", "signing", "secret", "api", "encryption", "access"}

# Environment variables surfaced in the config snapshot (redacted). Anything
# outside these prefixes is omitted to avoid leaking unrelated host env.
_CONFIG_PREFIXES = (
    "WATERTWIN_",
    "OT_",
    "VITE_",
    "HYDRAULIC_",
    "TREATMENT_",
    "S3M_",
    "KC_",
)

# scheme://user:password@host  ->  capture the password.
_URL_CRED_RE = re.compile(r"(?P<pre>[a-zA-Z][a-zA-Z0-9+.\-]*://[^:/@\s]+:)(?P<pw>[^@/\s]+)(?P<at>@)")


def _key_is_secret(name: str) -> bool:
    tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", name.lower()) if t]
    for i, token in enumerate(tokens):
        if token in _SECRET_TOKENS:
            return True
        if token in {"key", "cert"} and i > 0 and tokens[i - 1] in _PRIVATE_KEY_QUALIFIERS:
            return True
    return False


def redact_url_credentials(value: str) -> str:
    """Replace the password component of any URL in ``value``."""
    if not isinstance(value, str):
        return value
    return _URL_CRED_RE.sub(lambda m: f"{m.group('pre')}{REDACTED}{m.group('at')}", value)


def _url_passwords(value: str) -> list[str]:
    if not isinstance(value, str):
        return []
    return [m.group("pw") for m in _URL_CRED_RE.finditer(value)]


def collect_secret_values(env: Mapping[str, str]) -> set[str]:
    """Return literal secret strings to scrub from all free-text content."""
    values: set[str] = set()
    for name, value in env.items():
        if value is None:
            continue
        value = str(value)
        if _key_is_secret(name) and value:
            values.add(value)
        for pw in _url_passwords(value):
            if pw:
                values.add(pw)
    # Never treat an empty string as a secret to scrub.
    return {v for v in values if v}


def redact_env(env: Mapping[str, str]) -> dict[str, str]:
    """Return a redacted copy of the selected configuration environment."""
    out: dict[str, str] = {}
    for name in sorted(env):
        if not name.startswith(_CONFIG_PREFIXES):
            continue
        value = env[name]
        if value is None:
            out[name] = ""
            continue
        value = str(value)
        if _key_is_secret(name):
            out[name] = REDACTED
        else:
            out[name] = redact_url_credentials(value)
    return out


def redact_text(text: str, secret_values: set[str]) -> str:
    """Scrub every known secret literal from ``text``."""
    if not text:
        return text
    for secret in sorted(secret_values, key=len, reverse=True):
        if secret:
            text = text.replace(secret, REDACTED)
    return text


def _redact_json(obj, secret_values: set[str]):
    """Scrub secret literals from a JSON-serialisable structure."""
    if isinstance(obj, str):
        return redact_text(obj, secret_values)
    if isinstance(obj, dict):
        return {k: _redact_json(v, secret_values) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_json(v, secret_values) for v in obj]
    return obj


def _read_sbom_files(sbom_dir: str | None) -> dict[str, str]:
    files: dict[str, str] = {}
    if not sbom_dir or not os.path.isdir(sbom_dir):
        return files
    for name in sorted(os.listdir(sbom_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(sbom_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                files[name] = fh.read()
        except OSError:
            continue
    return files


def build_support_bundle(
    *,
    entitlements: dict,
    usage: dict,
    health: dict,
    audit_events: list[dict],
    config_env: Mapping[str, str] | None = None,
    log_lines: list[str] | None = None,
    sbom_dir: str | None = None,
) -> tuple[bytes, dict]:
    """Build a support-bundle ZIP (bytes) and return it with its manifest.

    All content is redacted: the config snapshot masks secret-named values and
    URL credentials, and every discovered secret literal is scrubbed from logs
    and audit payloads.
    """
    env = dict(config_env if config_env is not None else os.environ)
    secret_values = collect_secret_values(env)

    redacted_config = redact_env(env)
    redacted_logs = [redact_text(line, secret_values) for line in (log_lines or [])]
    redacted_audit = _redact_json(audit_events, secret_values)
    redacted_health = _redact_json(health, secret_values)
    redacted_entitlements = _redact_json(entitlements, secret_values)
    sbom_files = _read_sbom_files(sbom_dir)

    generated_at = datetime.now(UTC).isoformat()
    manifest = {
        "bundle": "s3m-watertwin-support-bundle",
        "generated_at": generated_at,
        "service": health.get("service", "watertwin-api"),
        "version": health.get("version"),
        "tenant_id": entitlements.get("tenant_id"),
        "plan": entitlements.get("plan"),
        "redaction": {
            "applied": True,
            "marker": REDACTED,
            "policy": (
                "Secret-named env values and URL credentials are masked; every "
                "discovered secret literal is scrubbed from logs and audit "
                "payloads. Support bundles never contain credentials."
            ),
            "secret_values_scrubbed": len(secret_values),
        },
        "contents": [
            "manifest.json",
            "config-snapshot.json",
            "health.json",
            "entitlements.json",
            "usage.json",
            "audit-tail.json",
            "logs/watertwin-api.log",
        ]
        + [f"sbom/{name}" for name in sbom_files],
        "control_boundary_note": (
            "Advisory/read-only platform. This bundle contains no control state "
            "and no path that could command plant equipment."
        ),
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("config-snapshot.json", json.dumps(redacted_config, indent=2, sort_keys=True))
        zf.writestr("health.json", json.dumps(redacted_health, indent=2))
        zf.writestr("entitlements.json", json.dumps(redacted_entitlements, indent=2))
        zf.writestr("usage.json", json.dumps(_redact_json(usage, secret_values), indent=2))
        zf.writestr("audit-tail.json", json.dumps(redacted_audit, indent=2))
        zf.writestr("logs/watertwin-api.log", "\n".join(redacted_logs))
        for name, content in sbom_files.items():
            zf.writestr(f"sbom/{name}", content)

    return buffer.getvalue(), manifest


__all__ = [
    "REDACTED",
    "build_support_bundle",
    "collect_secret_values",
    "redact_env",
    "redact_text",
    "redact_url_credentials",
]
