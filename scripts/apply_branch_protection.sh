#!/usr/bin/env bash
# Apply (or re-apply) branch protection on the default branch from the
# checked-in source of truth at .github/branch-protection/main.json.
#
# Why this exists: branch protection is a repository *setting*, not code, so it
# cannot be enforced by a merge alone. PR #56 merged a broken dashboard build
# because `main` was unprotected even though the blocking `dashboard` CI job
# existed. This script makes the protection policy reproducible, reviewable, and
# auditable: the desired state lives in git, and any maintainer with admin
# rights can apply it with one command.
#
# Requirements:
#   * gh (GitHub CLI) authenticated as a user/token WITH ADMIN on the repo.
#   * jq.
#
# Usage:
#   scripts/apply_branch_protection.sh                 # apply to Abraxas-S3M/S3M-WaterTwin main
#   REPO=owner/name BRANCH=main scripts/apply_branch_protection.sh
#
# The script is idempotent: applying it repeatedly converges to the same state.
set -euo pipefail

REPO="${REPO:-Abraxas-S3M/S3M-WaterTwin}"
BRANCH="${BRANCH:-main}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${CONFIG:-${SCRIPT_DIR}/../.github/branch-protection/${BRANCH}.json}"

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh (GitHub CLI) is not installed or not on PATH." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "error: jq is not installed or not on PATH." >&2
  exit 1
fi

if [[ ! -f "${CONFIG}" ]]; then
  echo "error: branch-protection config not found: ${CONFIG}" >&2
  exit 1
fi

echo ">> Repo:    ${REPO}"
echo ">> Branch:  ${BRANCH}"
echo ">> Config:  ${CONFIG}"
echo

echo ">> Current protected state (before):"
gh api "repos/${REPO}/branches/${BRANCH}" --jq '.protected'
echo

echo ">> Applying branch protection..."
# Feed the checked-in JSON straight to the protection endpoint. A non-admin
# token returns 403/404 here; we surface that error rather than working around
# it.
if ! gh api -X PUT "repos/${REPO}/branches/${BRANCH}/protection" \
  -H "Accept: application/vnd.github+json" \
  --input "${CONFIG}" >/tmp/branch-protection-result.json; then
  echo >&2
  echo "error: failed to apply branch protection." >&2
  echo "       A 403/404 usually means the gh login lacks ADMIN on ${REPO}." >&2
  exit 1
fi

echo
echo ">> Verification — .protected:"
gh api "repos/${REPO}/branches/${BRANCH}" --jq '.protected'
echo
echo ">> Verification — required_status_checks:"
gh api "repos/${REPO}/branches/${BRANCH}/protection" --jq '.required_status_checks'
echo
echo ">> Done. Branch protection on ${REPO}@${BRANCH} matches ${CONFIG}."
