# Branch protection policy (`main`)

## Why this exists

CI jobs can only *report* status; they cannot stop a merge on their own. Stopping
a merge is a repository **setting** — branch protection — that must be turned on
separately from the workflow that defines the checks.

On this repository that setting was **off**:

```console
$ gh api repos/Abraxas-S3M/S3M-WaterTwin/branches/main --jq '.protected'
false
```

Because `main` was unprotected, **PR #56 merged with a completely broken
dashboard build** even though the blocking `dashboard` CI job existed and was
failing. The gate was there; nothing was enforcing it.

This document, the machine-readable policy at
[`.github/branch-protection/main.json`](../../.github/branch-protection/main.json),
the [`scripts/apply_branch_protection.sh`](../../scripts/apply_branch_protection.sh)
helper, and the [`Apply branch protection`](../../.github/workflows/branch-protection.yml)
workflow make the policy explicit, version-controlled, and reproducible.

## The policy

`main` must be protected with:

| Setting | Value | Effect |
| --- | --- | --- |
| `required_status_checks.strict` | `true` | PR branches must be up to date with `main` before merging, so the merge *result* is re-tested. |
| `required_status_checks.contexts` | the build gates listed below | Merges are blocked unless these checks pass. |
| `enforce_admins` | `true` | Admins are held to the same rules — no bypass. |
| `required_linear_history` | `true` | No merge commits; keeps history bisectable. |
| `allow_force_pushes` | `false` | History cannot be rewritten. |
| `allow_deletions` | `false` | `main` cannot be deleted. |
| `required_pull_request_reviews` | `null` | Not required by this policy (change here if reviews are desired). |
| `restrictions` | `null` | No push allow-list. |

### Required status check contexts

A required "context" must match a check-run name **exactly**. GitHub derives each
check-run name from the job's `name:` field, and matrix jobs get one check per
matrix entry. So the short job ids (`dashboard`, `import-guard`, ...) are **not**
valid contexts — the real, verified names are:

- `compile-guard (compileall packages + services)`
- `import-guard (watertwin-api)`
- `import-guard (hydraulic-sim)`
- `import-guard (treatment-sim)`
- `import-guard (edge-gateway)`
- `quality (watertwin-api)`
- `quality (hydraulic-sim)`
- `quality (treatment-sim)`
- `quality (edge-gateway)`
- `packages (shared physics + contracts)`
- `dashboard (React/TS — lint + test + build, blocking)`

> Note: requiring a context that never reports (e.g. the bare string `dashboard`)
> would leave every PR permanently "Expected — waiting for status" and block all
> merges. The names above were confirmed against actual check runs on `main`:
> `gh api repos/Abraxas-S3M/S3M-WaterTwin/commits/main/check-runs --jq '.check_runs[].name'`.

To require additional gates (for example `security-ingest`, `helm`, `sbom`,
`vuln-scan`, `secret-scan`), add their exact check-run names to
`.github/branch-protection/main.json` and re-apply.

## How to apply it

Applying branch protection requires **admin** rights on the repository. It is
therefore a maintainer action; it cannot be done by an ordinary CI token or by
merging a file.

### Option A — one command locally

Authenticate `gh` as a user/token with admin on the repo, then run:

```bash
scripts/apply_branch_protection.sh
```

The script prints the before/after state and the resulting `required_status_checks`.
It is idempotent — re-running it converges to the policy in the JSON file.

### Option B — from the Actions tab

1. Add a repository (or org) secret named `ADMIN_TOKEN`: a fine-grained or
   classic PAT from a user with admin on the repo, granting
   **Administration: read/write**.
2. Actions → **Apply branch protection** → **Run workflow** (default branch `main`).

## How to verify

```bash
gh api repos/Abraxas-S3M/S3M-WaterTwin/branches/main --jq '.protected'
gh api repos/Abraxas-S3M/S3M-WaterTwin/branches/main/protection --jq '.required_status_checks'
```

The first must print `true`; the second must list the required contexts above
with `"strict": true`.

## Troubleshooting

- **`403`/`404` when applying** — the authenticated identity lacks admin on the
  repo. Do not work around it; use an admin identity/token.
- **A PR shows "Expected — waiting for status" forever** — a required context name
  does not match any real check-run name. Reconcile the contexts in the JSON with
  the output of the `check-runs` command above.
