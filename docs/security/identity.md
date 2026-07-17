# Identity &amp; Role-Based Access Control (Commercial Hardening #1)

WaterTwin adds **identity** and **role-based access control (RBAC)** via
[Keycloak](https://www.keycloak.org/) across `services/watertwin-api` and
`apps/dashboard`. This hardens *who* may read an advisory view or record an
operator approval — **without changing the advisory / read-only safety
boundary**. Authentication and authorization decide which authenticated humans
may act; they never introduce a control-write path. Every recommendation
remains advisory and `human_review_required`, and every response still carries
`control_write_enabled=false` (see
[`control-boundaries.md`](./control-boundaries.md)).

## Components

| Piece | Where | Role |
| --- | --- | --- |
| Keycloak | `docker-compose.yml` (`keycloak`) | Identity provider / OIDC + JWT issuer |
| Seeded realm | `infrastructure/keycloak/watertwin-realm.json` | Dev realm `watertwin`, roles, and one dev user per role |
| API auth | `services/watertwin-api/app/auth.py` | JWT bearer validation (JWKS/RS256), `get_current_user`, `require_role` |
| Dashboard auth | `apps/dashboard/src/auth/*` | OIDC login, in-memory token, bearer on API calls, role gating |

## Roles

Six realm roles are seeded in the `watertwin` realm:

| Role | Grants |
| --- | --- |
| `viewer` | Read all advisory views (status, telemetry, analytics, WQ, equipment, membrane, energy, resilience, executive, assistant). |
| `operator` | Everything a viewer can, **plus** approve/reject recommendations. |
| `engineer` | Everything a viewer can, **plus** run what-if scenarios and reset demo state. |
| `auditor` | Everything a viewer can, **plus** read the audit trail. |
| `security` | Everything a viewer can, **plus** read the cyber-physical security analytics and export the signed SIEM feed. |
| `admin` | Superset of all roles. |

## Tenant &amp; facility scoping (multi-tenancy)

Roles decide *what a caller may do*; **tenant / facility membership** decides
*what data a caller may see*. The two are orthogonal — an `admin` of one tenant
still may not read another tenant's data. Every canonical record and persisted
row (`audit_event`, `recommendation`, `telemetry`) carries a `tenant_id` /
`facility_id`, and reads are **row-level scoped** so cross-tenant access is
denied (`403`) at the API layer before any store query runs.

Membership is carried in the access token and extracted in `auth.py`:

| Claim (any accepted) | Meaning |
| --- | --- |
| `tenant_ids` / `tenants` / `tenant_id` / `tenant` | Tenants the caller may read (list, scalar, or CSV). |
| `facility_ids` / `facilities` / `facility_id` / `facility` | Facilities the caller may read. |

Resolution rules (backward compatible):

- A token with **no tenant claim** is treated as a member of the single default
  tenant (`s3m-default`) with access to every facility in it — so legacy
  single-facility tokens keep working unchanged.
- A token with tenant claims but **no facility claim** may read every facility
  *within its tenants*.
- The dev bypass (`WATERTWIN_AUTH_DISABLED=true`) runs as a wildcard
  (`*`) admin with access to all tenants/facilities.

Scoped read/write surfaces:

- **Analytics** (`water-quality/*`, `equipment/*`, `membrane/*`,
  `maintenance/*`, `energy/*`, `resilience/*`, `executive/*`) accept optional
  `tenant_id` / `facility_id` query parameters (defaulting to the platform
  defaults) and echo the resolved scope in the response envelope.
- **Config** (`recommendations`, `recommendations/{id}`) only ever lists /
  returns records inside the caller's tenant/facility.
- **Audit** (`audit`) is filtered to the caller's tenant (and optional
  facility); an auditor of one tenant can never read another's trail. The
  tamper-evident hash chain is a single global chain and `audit/verify` still
  verifies it in full — `tenant_id` / `facility_id` are stored *alongside* the
  hashed event core, never inside it, so scoping leaves the chain invariant
  unchanged.

Pre-existing single-facility data is migrated into the default tenant/facility
on connect (`store.py` backfill + `infrastructure/database/init.sql`), so nothing
breaks on upgrade.

## RBAC matrix (enforced in `watertwin-api`)

| Endpoint(s) | Method | Required role |
| --- | --- | --- |
| `/health` | GET | none (liveness; used by container health checks) |
| Read views: `simulation-center/network`, `recommendations`, `recommendations/{id}`, `water-quality/*`, `equipment/*`, `membrane/*`, `maintenance/*`, `energy/*`, `resilience/criticality`, `resilience/generator`, `resilience/grid-outage`, `executive/*`, `reports/scenario/{id}` | GET / POST (advisory what-if only) | any authenticated role |
| `recommendations/{id}/decision` (approve/reject) | POST | `operator` or `admin` |
| `simulation-center/run` (scenario) | POST | `engineer` or `admin` |
| `reset` | POST | `engineer` or `admin` |
| `audit` (read audit trail), `audit/verify` | GET | `auditor` or `admin` |
| `security/overview` (cyber-physical security posture), `security/siem-export` (signed SIEM export) | GET | `security` or `admin` |

Notes:

- The `security` views are **monitoring only**: they read the existing
  cyber-physical + anomaly signals (sensor-confidence, telemetry-vs-hydraulic
  consistency, source-health) and export the immutable audit log as a signed,
  append-only JSON/CEF feed. There is no control-write path.

- `admin` satisfies every check (it is the superset role).
- The POST endpoints that *compute* advisory what-ifs (`energy/optimize`,
  `resilience/grid-outage`, `reports/scenario/{id}`) are treated as **reads**:
  they require any authenticated role but no elevated role, because they never
  write to control and only produce advisory output. Running the
  baseline-vs-scenario hydraulic simulation (`simulation-center/run`) is the
  gated "scenario" action.
- Missing/invalid token on a protected endpoint → **401**. Authenticated but
  under-privileged → **403**.

## Dev users (seeded)

Each user's password equals their username (dev only — never for production):

| Username | Password | Realm roles |
| --- | --- | --- |
| `viewer` | `viewer` | `viewer` |
| `operator` | `operator` | `viewer`, `operator` |
| `engineer` | `engineer` | `viewer`, `engineer` |
| `auditor` | `auditor` | `viewer`, `auditor` |
| `security` | `security` | `viewer`, `security` |
| `admin` | `admin` | `viewer`, `operator`, `engineer`, `auditor`, `security`, `admin` |

## Enforced vs. dev-bypass mode

Authentication is controlled by the `WATERTWIN_AUTH_DISABLED` environment
variable on `watertwin-api`:

- **Enforced (default; unset or `false`)** — every protected endpoint requires a
  valid Keycloak JWT. The active mode is logged at startup
  (`authentication ENFORCED ...`).
- **Dev bypass (`WATERTWIN_AUTH_DISABLED=true`)** — authentication is skipped and
  every request runs as a synthetic `admin` principal (`dev-admin`). This keeps
  local development and the pre-identity test-suites working. The bypass is an
  explicit, logged opt-out (`authentication DISABLED (dev bypass) ...`) and is
  **never** the production default.

CI runs the standard suites under the dev bypass (see
`services/watertwin-api/conftest.py`, which sets the default), plus the
dedicated enforced-auth suite `tests/test_auth.py`.

## API configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `WATERTWIN_AUTH_DISABLED` | `true` enables the dev bypass | unset → enforced |
| `WATERTWIN_OIDC_ISSUER` | Expected token issuer (`iss`), e.g. `http://localhost:8180/realms/watertwin` | unset |
| `WATERTWIN_OIDC_JWKS_URI` | JWKS endpoint (defaults to `<issuer>/protocol/openid-connect/certs`) | derived from issuer |
| `WATERTWIN_OIDC_AUDIENCE` | Optional expected `aud`; audience verification is skipped when unset | unset |
| `WATERTWIN_OIDC_PUBLIC_KEY` | Static PEM public key (air-gapped / test alternative to a live JWKS) | unset |

In `docker-compose.yml` the issuer is the browser-facing Keycloak URL
(`http://localhost:8180/realms/watertwin`) while the JWKS is fetched over the
internal docker network (`http://keycloak:8080/...`), so the `iss` claim matches
regardless of which side validates.

## Dashboard configuration (build-time `VITE_*`)

| Variable | Purpose |
| --- | --- |
| `VITE_KEYCLOAK_URL` | Keycloak base URL (e.g. `http://localhost:8180`) |
| `VITE_KEYCLOAK_REALM` | Realm (`watertwin`) |
| `VITE_KEYCLOAK_CLIENT_ID` | Public client (`watertwin-dashboard`) |

When these are unset the dashboard renders without a login gate (matching the
API dev bypass), which is how the component test-suite runs. When set, the
dashboard shows a login screen, performs the OIDC authorization-code + PKCE
flow, keeps the token **in memory only** (never `localStorage`/`sessionStorage`
or cookies), attaches it as a bearer to every API call, shows the current user
and role in the shell, gates the approve/reject and scenario/reset controls by
role, and surfaces a clear message on 401/403.

## Local setup

```bash
# 1) Bring up the full stack (Keycloak + seeded realm + auth-enforced API + UI).
docker compose up --build

# 2) Open the dashboard and log in with a seeded dev user.
open http://localhost:8080          # dashboard (login gate)
open http://localhost:8180          # Keycloak admin console (admin/admin)

# 3) Or drive the API directly with a token (direct grant is enabled for dev):
TOKEN=$(curl -s http://localhost:8180/realms/watertwin/protocol/openid-connect/token \
  -d grant_type=password -d client_id=watertwin-dashboard \
  -d username=operator -d password=operator | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/water-quality/status
```

To run the API locally without Keycloak, set `WATERTWIN_AUTH_DISABLED=true`.

## What this does NOT change

- **No control write.** RBAC gates advisory reads and operator approvals only;
  there is still no path that commands a PLC/SCADA/VFD/valve/pump/dosing system.
- **No weakened boundary.** Every response still reports
  `control_write_enabled=false` and `operator_approval_required=true`; the CI
  boundary guard remains in force.
- **No tokens in browser storage.** The dashboard holds the access token in
  memory for the session only.
