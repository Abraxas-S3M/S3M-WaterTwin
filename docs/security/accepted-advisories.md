# Accepted Security Advisories

This document is the audited record of security-scan findings that have been
**reviewed and accepted** (temporarily suppressed) so CI can stay green without
silently hiding risk. The CI supply-chain gates fail the build on any finding
that is *not* listed in the corresponding ignore file.

Do not add an entry without a justification and a review date. Prefer upgrading
the affected dependency over accepting an advisory.

## Gates and their ignore files

| Gate | Tool | Ignore file | CI job |
|------|------|-------------|--------|
| Python dependency vulnerabilities | `pip-audit` | `security/pip-audit-ignore.txt` | `vuln-scan` |
| npm dependency vulnerabilities | `npm audit` (+ `scripts/npm_audit_gate.py`) | `security/npm-audit-ignore.txt` | `vuln-scan` |
| Secrets | `gitleaks` | `.gitleaks.toml` (`[allowlist]`) | `secret-scan` |

## How to accept an advisory

1. Confirm the advisory is not exploitable in our usage (advisory-only,
   read-only what-if platform) or that no fixed version is yet available.
2. Add the advisory ID to the matching ignore file:
   - Python: add the `GHSA-…` / `PYSEC-…` id to `security/pip-audit-ignore.txt`.
   - npm: add the `GHSA-…` id (or advisory URL/source id) to
     `security/npm-audit-ignore.txt`.
   - Secret false-positive: add a narrowly-scoped path/regex to the
     `[allowlist]` in `.gitleaks.toml`.
3. Add a row to the table below with the justification and review date.
4. Open a follow-up to remove the suppression once a fix is available.

## Accepted Python advisories (`pip-audit`)

| Advisory | Package | Justification | Accepted on | Review by |
|----------|---------|---------------|-------------|-----------|
| _(none)_ | | | | |

## Accepted npm advisories (`npm audit`)

| Advisory | Package | Justification | Accepted on | Review by |
|----------|---------|---------------|-------------|-----------|
| _(none)_ | | | | |

## Accepted secret-scan findings (`gitleaks`)

| Path / pattern | What it is | Justification | Accepted on |
|----------------|-----------|---------------|-------------|
| `.env.example` | Placeholder env values | Example file; contains no real secrets. | 2026-07-17 |
| `infrastructure/keycloak/watertwin-realm.json` | Demo realm users | Local-only demo credentials (viewer/operator/engineer/admin/auditor); not used in production. | 2026-07-17 |
| `docs/licensing/sbom/*.cdx.json` | SBOM integrity hashes | CycloneDX hashes, not secrets. | 2026-07-17 |
| `apps/dashboard/package-lock.json` | npm integrity hashes | Lockfile integrity hashes, not secrets. | 2026-07-17 |
