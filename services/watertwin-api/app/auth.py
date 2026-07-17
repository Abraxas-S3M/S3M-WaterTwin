"""Identity + role-based access control for watertwin-api.

Commercial-hardening work package #1. This module adds Keycloak-backed identity
to the *advisory, read-only* API without changing its safety posture: it gates
**who** may read an advisory view or record an operator approval, but it never
introduces a control-write path. Every recommendation is still advisory and
requires human approval; authorization only decides which authenticated humans
may make that call.

Two modes, selected by the ``WATERTWIN_AUTH_DISABLED`` environment variable:

* **Enforced (default)** — ``WATERTWIN_AUTH_DISABLED`` unset or ``false``. Every
  protected endpoint requires a valid Keycloak-issued JWT bearer token. Roles
  are extracted from the token and checked against the endpoint's required
  roles (see the RBAC matrix in ``main.py``).

* **Dev bypass** — ``WATERTWIN_AUTH_DISABLED=true``. Authentication is skipped
  and every request runs as a synthetic ``admin`` principal. This keeps local
  development and the existing test-suites working without a running Keycloak.
  It is an explicit, logged opt-out — never the production default.

Tokens are validated against Keycloak's JWKS (RS256) by default. For tests and
air-gapped setups, a static PEM public key may be supplied via
``WATERTWIN_OIDC_PUBLIC_KEY`` instead of a live JWKS endpoint.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("watertwin.auth")

# The advisory roles seeded in the Keycloak "watertwin" realm. The multi-facility
# roles gate the fleet administration surface: ``tenant-admin`` manages every
# facility within its tenant, while ``facility-operator`` is scoped to the
# specific facility (or facilities) assigned to it.
ROLES: frozenset[str] = frozenset(
    {
        "viewer",
        "operator",
        "engineer",
        "admin",
        "auditor",
        "tenant-admin",
        "facility-operator",
    }
)

# Roles permitted to manage / view the whole fleet within their tenant.
FACILITY_MANAGER_ROLES: frozenset[str] = frozenset({"tenant-admin", "admin"})

# Dev-bypass tenant so the multi-facility surfaces work without Keycloak.
DEV_TENANT_ID = "TEN-ACME"

_JWT_ALGORITHMS = ["RS256"]


# --------------------------------------------------------------------------- #
# Configuration (read from the environment at request time so tests and
# deployments can flip modes without re-importing the module).
# --------------------------------------------------------------------------- #


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def auth_disabled() -> bool:
    """True when the explicit dev-mode bypass is active."""
    return _env_bool("WATERTWIN_AUTH_DISABLED", False)


def oidc_issuer() -> Optional[str]:
    return _env("WATERTWIN_OIDC_ISSUER")


def oidc_audience() -> Optional[str]:
    return _env("WATERTWIN_OIDC_AUDIENCE")


def oidc_jwks_uri() -> Optional[str]:
    explicit = _env("WATERTWIN_OIDC_JWKS_URI")
    if explicit:
        return explicit
    issuer = oidc_issuer()
    if issuer:
        return issuer.rstrip("/") + "/protocol/openid-connect/certs"
    return None


def oidc_public_key() -> Optional[str]:
    """Static PEM public key (test / air-gapped alternative to a live JWKS)."""
    return _env("WATERTWIN_OIDC_PUBLIC_KEY")


# --------------------------------------------------------------------------- #
# Principal
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Principal:
    """The authenticated (or synthetic dev) identity behind a request."""

    username: str
    roles: frozenset[str]
    subject: Optional[str] = None
    email: Optional[str] = None
    auth_mode: str = "keycloak"
    # Multi-tenant / multi-facility scope carried by the identity token.
    tenant_id: Optional[str] = None
    # Facilities the identity is explicitly entitled to. Empty means "all
    # facilities within the tenant" for facility managers; for a
    # facility-operator it is the specific facility (or facilities) assigned.
    facility_ids: frozenset[str] = frozenset()

    def has_any(self, *required: str) -> bool:
        return bool(self.roles.intersection(required))

    def can_manage_facilities(self) -> bool:
        """True for tenant-admins / platform admins (fleet-wide within tenant)."""
        return bool(self.roles.intersection(FACILITY_MANAGER_ROLES))

    @property
    def actor(self) -> str:
        """Stable identifier recorded in the audit trail for this principal."""
        return self.username or self.subject or "unknown"


# The synthetic principal used only when the dev bypass is active. It carries
# every role so existing flows keep working, and is clearly labelled so the
# audit trail never mistakes it for a real Keycloak identity.
SYNTHETIC_ADMIN = Principal(
    username="dev-admin",
    roles=ROLES,
    subject="dev-admin",
    email=None,
    auth_mode="dev-bypass",
    tenant_id=DEV_TENANT_ID,
    facility_ids=frozenset(),
)


# --------------------------------------------------------------------------- #
# Token verification
# --------------------------------------------------------------------------- #

_jwks_lock = threading.Lock()
_jwks_client: Optional[tuple[str, "jwt.PyJWKClient"]] = None


def _get_jwks_signing_key(token: str, jwks_uri: str):
    """Resolve (and cache) the JWKS signing key for ``token``."""
    global _jwks_client
    with _jwks_lock:
        if _jwks_client is None or _jwks_client[0] != jwks_uri:
            _jwks_client = (jwks_uri, jwt.PyJWKClient(jwks_uri))
        client = _jwks_client[1]
    return client.get_signing_key_from_jwt(token).key


def _resolve_key(token: str):
    """Return the verification key + algorithms for ``token``.

    A static PEM public key takes precedence when configured (used by tests and
    air-gapped deployments); otherwise Keycloak's JWKS endpoint is consulted.
    """
    pem = oidc_public_key()
    if pem:
        return pem
    jwks_uri = oidc_jwks_uri()
    if not jwks_uri:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "authentication is enforced but no OIDC issuer/JWKS is configured; "
                "set WATERTWIN_OIDC_ISSUER (or WATERTWIN_OIDC_JWKS_URI), or enable "
                "the dev bypass with WATERTWIN_AUTH_DISABLED=true"
            ),
        )
    return _get_jwks_signing_key(token, jwks_uri)


def _decode(token: str) -> dict:
    key = _resolve_key(token)
    options = {"verify_aud": bool(oidc_audience())}
    try:
        return jwt.decode(
            token,
            key,
            algorithms=_JWT_ALGORITHMS,
            audience=oidc_audience(),
            issuer=oidc_issuer(),
            options=options,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid bearer token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _roles_from_claims(claims: dict) -> frozenset[str]:
    """Extract realm + client roles from a Keycloak access token."""
    roles: set[str] = set()
    realm_access = claims.get("realm_access") or {}
    if isinstance(realm_access, dict):
        roles.update(realm_access.get("roles", []) or [])
    resource_access = claims.get("resource_access") or {}
    if isinstance(resource_access, dict):
        for entry in resource_access.values():
            if isinstance(entry, dict):
                roles.update(entry.get("roles", []) or [])
    return frozenset(r for r in roles if isinstance(r, str))


def _tenant_from_claims(claims: dict) -> Optional[str]:
    tenant = claims.get("tenant_id") or claims.get("tenant")
    return tenant if isinstance(tenant, str) and tenant else None


def _facility_ids_from_claims(claims: dict) -> frozenset[str]:
    raw = claims.get("facility_ids")
    if raw is None:
        raw = claims.get("facilities")
    if not isinstance(raw, (list, tuple, set)):
        return frozenset()
    return frozenset(v for v in raw if isinstance(v, str) and v)


def _principal_from_claims(claims: dict) -> Principal:
    username = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("sub")
        or "unknown"
    )
    return Principal(
        username=username,
        roles=_roles_from_claims(claims),
        subject=claims.get("sub"),
        email=claims.get("email"),
        auth_mode="keycloak",
        tenant_id=_tenant_from_claims(claims),
        facility_ids=_facility_ids_from_claims(claims),
    )


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #

# ``auto_error=False`` so we can return a 401 with a WWW-Authenticate header and
# a clear message rather than FastAPI's default 403 for a missing credential.
_bearer_scheme = HTTPBearer(auto_error=False, description="Keycloak JWT bearer token")


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Principal:
    """Resolve the caller's identity.

    * Dev bypass active -> synthetic ``admin`` principal.
    * Otherwise a valid Keycloak JWT bearer token is required (401 if missing or
      invalid); roles are extracted from the token.
    """
    if auth_disabled():
        return SYNTHETIC_ADMIN

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = _decode(credentials.credentials)
    return _principal_from_claims(claims)


def require_role(*required: str):
    """Return a dependency that admits only principals holding one of ``required``.

    ``admin`` is always accepted. Under the dev bypass the synthetic admin
    satisfies every check.
    """
    allowed = frozenset(required) | {"admin"}

    def _dependency(user: Principal = Depends(get_current_user)) -> Principal:
        if not user.has_any(*allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "insufficient role: this action requires one of "
                    f"{sorted(required)}; caller has {sorted(user.roles)}"
                ),
            )
        return user

    return _dependency


def log_auth_mode() -> None:
    """Log which authentication mode is active (called at app startup)."""
    if auth_disabled():
        logger.warning(
            "authentication DISABLED (dev bypass): requests run as synthetic "
            "admin '%s'. Do not use in production.",
            SYNTHETIC_ADMIN.username,
        )
    else:
        logger.info(
            "authentication ENFORCED: validating Keycloak JWTs (issuer=%s, jwks=%s)",
            oidc_issuer() or "<unset>",
            "static-key" if oidc_public_key() else (oidc_jwks_uri() or "<unset>"),
        )
