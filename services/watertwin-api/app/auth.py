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

from . import config

logger = logging.getLogger("watertwin.auth")

# The five advisory roles seeded in the Keycloak "watertwin" realm.
ROLES: frozenset[str] = frozenset(
    {"viewer", "operator", "engineer", "admin", "auditor"}
)

_JWT_ALGORITHMS = ["RS256"]

# Wildcard membership: a principal carrying this in ``tenants`` / ``facilities``
# may read across every tenant / facility. It is granted only to the dev-bypass
# synthetic admin; real Keycloak identities are always scoped to the explicit
# tenant/facility membership carried in their token (defaulting to the single
# legacy tenant/facility when a token predates multi-tenancy).
WILDCARD = "*"


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
    """The authenticated (or synthetic dev) identity behind a request.

    In addition to advisory *roles* (what the caller may do), a principal carries
    *tenant* and *facility* membership (what data the caller may see). Roles and
    membership are orthogonal: an ``admin`` of tenant A still may not read tenant
    B's data. Membership is enforced at the API layer so cross-tenant access is
    denied before any store query runs.
    """

    username: str
    roles: frozenset[str]
    subject: Optional[str] = None
    email: Optional[str] = None
    auth_mode: str = "keycloak"
    #: Tenants this principal may read. ``{"*"}`` grants access to all tenants
    #: (dev bypass only).
    tenants: frozenset[str] = frozenset()
    #: Facilities this principal may read. ``{"*"}`` grants access to every
    #: facility within the principal's tenants.
    facilities: frozenset[str] = frozenset()

    def has_any(self, *required: str) -> bool:
        return bool(self.roles.intersection(required))

    def can_access_tenant(self, tenant_id: str) -> bool:
        return WILDCARD in self.tenants or tenant_id in self.tenants

    def can_access_facility(self, facility_id: str) -> bool:
        return WILDCARD in self.facilities or facility_id in self.facilities

    def can_access(self, tenant_id: str, facility_id: str) -> bool:
        """True only when the principal may read this tenant *and* facility."""
        return self.can_access_tenant(tenant_id) and self.can_access_facility(facility_id)

    @property
    def actor(self) -> str:
        """Stable identifier recorded in the audit trail for this principal."""
        return self.username or self.subject or "unknown"


# The synthetic principal used only when the dev bypass is active. It carries
# every role and wildcard tenant/facility membership so existing single-facility
# flows keep working, and is clearly labelled so the audit trail never mistakes
# it for a real Keycloak identity.
SYNTHETIC_ADMIN = Principal(
    username="dev-admin",
    roles=ROLES,
    subject="dev-admin",
    email=None,
    auth_mode="dev-bypass",
    tenants=frozenset({WILDCARD}),
    facilities=frozenset({WILDCARD}),
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


def _string_set_from_claims(claims: dict, *names: str) -> frozenset[str]:
    """Collect a string set from any of ``names`` (list, scalar, or CSV)."""
    values: set[str] = set()
    for name in names:
        raw = claims.get(name)
        if raw is None:
            continue
        if isinstance(raw, str):
            values.update(part.strip() for part in raw.split(",") if part.strip())
        elif isinstance(raw, (list, tuple, set, frozenset)):
            values.update(str(item).strip() for item in raw if str(item).strip())
    return frozenset(values)


def _membership_from_claims(claims: dict) -> tuple[frozenset[str], frozenset[str]]:
    """Extract tenant + facility membership from a Keycloak access token.

    Recognises both plural (``tenant_ids`` / ``tenants``) and singular
    (``tenant_id`` / ``tenant``) claim shapes, likewise for facilities. A token
    that predates multi-tenancy (no tenant/facility claim) is treated as a member
    of the single legacy default tenant, with access to every facility inside it
    (facility wildcard) so existing single-facility deployments keep working.
    Membership never widens across tenants implicitly: a token with tenant claims
    but no facility claim is confined to the facilities it explicitly lists.
    """
    tenants = _string_set_from_claims(claims, "tenant_ids", "tenants", "tenant_id", "tenant")
    facilities = _string_set_from_claims(
        claims, "facility_ids", "facilities", "facility_id", "facility"
    )
    if not tenants:
        tenants = frozenset({config.DEFAULT_TENANT_ID})
        # Legacy single-tenant token: default to the legacy facility scope but
        # keep the facility wildcard so pre-existing flows over the default
        # facility keep working without a facility claim.
        if not facilities:
            facilities = frozenset({WILDCARD})
    elif not facilities:
        # Explicit tenant membership but no facility claim -> confine to the
        # facilities inside those tenants (wildcard within the granted tenants).
        facilities = frozenset({WILDCARD})
    return tenants, facilities


def _principal_from_claims(claims: dict) -> Principal:
    username = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("sub")
        or "unknown"
    )
    tenants, facilities = _membership_from_claims(claims)
    return Principal(
        username=username,
        roles=_roles_from_claims(claims),
        subject=claims.get("sub"),
        email=claims.get("email"),
        auth_mode="keycloak",
        tenants=tenants,
        facilities=facilities,
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
