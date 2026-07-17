# Signed-update channel

WaterTwin ships a **signed-update channel reference**: how a deployment learns
about, and cryptographically verifies, a new release before it is applied.

Implementation: [`services/watertwin-api/app/updates.py`](../../services/watertwin-api/app/updates.py).

## Two non-negotiable rules

1. **Verify before apply.** An update manifest is only trustworthy once its
   Ed25519 signature is verified against the deployment's configured release
   public key.
2. **Never auto-update in production.** This service does **not** download,
   unpack, or apply updates. It only *reports* channel status and *verifies* a
   supplied manifest. Applying a verified release is an out-of-band,
   operator-driven action (roll the container image / redeploy). There is no
   code path in the service that mutates the running deployment.

Because there is no apply/download path, an update mechanism can never become a
backdoor into the advisory/read-only platform.

## Signature scheme

* **Algorithm:** Ed25519.
* **Signed bytes:** the *canonical* JSON encoding of the manifest — sorted keys,
  no insignificant whitespace (`updates.canonical_manifest_bytes`).
* **Signature encoding:** hex.
* **Release public key:** `WATERTWIN_UPDATE_PUBLIC_KEY` (PEM) or
  `WATERTWIN_UPDATE_PUBLIC_KEY_HEX` (32-byte raw key, hex).

### Manifest shape (example)

```json
{
  "version": "0.2.0",
  "channel": "stable",
  "released_at": "2026-07-01T00:00:00Z",
  "artifact": "s3m-watertwin/watertwin-api:0.2.0",
  "sha256": "<image digest>"
}
```

## Endpoints (admin)

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/admin/update-channel` | Report channel status: current version, channel, `auto_update_enabled=false`, `verify_before_apply=true`, release-key fingerprint, and the policy text. |
| `POST /api/v1/admin/update-channel/verify` | Verify a supplied `{manifest, signature, public_key?}`. Returns `{verified, reason, fingerprint, applied:false}`. **Never applies.** |

Every verification is recorded in the audit trail
(`update.signature.verified`, `applied=false`).

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `WATERTWIN_UPDATE_CHANNEL` | Channel name reported to the UI | `stable` |
| `WATERTWIN_UPDATE_PUBLIC_KEY` | Release public key (PEM) | unset |
| `WATERTWIN_UPDATE_PUBLIC_KEY_HEX` | Release public key (raw hex) | unset |

## Applying an update (operator runbook)

1. Obtain the new release manifest + signature from the vendor channel.
2. Verify it: `POST /api/v1/admin/update-channel/verify` (or offline with the
   published public key). Proceed **only** if `verified=true`.
3. Confirm the image digest (`sha256`) matches the artifact you will deploy.
4. Roll the deployment out-of-band (e.g. update the image tag in
   `docker-compose.yml` / your orchestrator and redeploy). The service never
   does this for you.

Tests: `services/watertwin-api/tests/test_updates.py` (valid signature, tampered
manifest, wrong key, missing key; endpoint verify without apply).
