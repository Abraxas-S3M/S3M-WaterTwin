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

Five realm roles are seeded in the `watertwin` realm:

| Role | Grants |
| --- | --- |
| `viewer` | Read all advisory views (status, telemetry, analytics, WQ, equipment, membrane, energy, resilience, executive, assistant). |
| `operator` | Everything a viewer can, **plus** approve/reject recommendations. |
| `engineer` | Everything a viewer can, **plus** run what-if scenarios and reset demo state. |
| `auditor` | Everything a viewer can, **plus** read the audit trail. |
| `admin` | Superset of all roles. |

## RBAC matrix (enforced in `watertwin-api`)

| Endpoint(s) | Method | Required role |
| --- | --- | --- |
| `/health` | GET | none (liveness; used by container health checks) |
| Read views: `simulation-center/network`, `recommendations`, `recommendations/{id}`, `water-quality/*`, `equipment/*`, `membrane/*`, `maintenance/*`, `energy/*`, `resilience/criticality`, `resilience/generator`, `resilience/grid-outage`, `executive/*`, `reports/scenario/{id}` | GET / POST (advisory what-if only) | any authenticated role |
| `recommendations/{id}/decision` (approve/reject) | POST | `operator` or `admin` |
| `simulation-center/run` (scenario) | POST | `engineer` or `admin` |
| `reset` | POST | `engineer` or `admin` |
| `audit` (read audit trail) | GET | `auditor` or `admin` |

Notes:

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
| `admin` | `admin` | `viewer`, `operator`, `engineer`, `auditor`, `admin` |

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
