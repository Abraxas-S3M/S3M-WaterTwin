"""Identity + role-based access control for watertwin-ingest.

Reuses the **same** Keycloak OIDC / role model as watertwin-api (RS256 JWTs
validated against the realm JWKS, or a static PEM public key for tests /
air-gapped setups). It gates *who* may push a file into the intake surface; it
never introduces a control-write path and never reaches OT.

RBAC for the ingest surface:

* ``engineer`` / ``admin`` -> may upload (and read).
* ``operator``            -> may read upload history only (never upload).
* ``viewer`` / ``security`` (and any other role) -> **no access at all**. Every
  ingest route answers ``404`` (not ``403``) for them so the surface's very
  existence is not disclosed.

The caller's ``tenant_id`` is always bound from the token at intake and is never
accepted from the request body. Cross-tenant reads are denied.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config

logger = logging.getLogger("watertwin.ingest.auth")

# Roles permitted to upload a file to the intake surface.
UPLOAD_ROLES: frozenset[str] = frozenset({"engineer", "admin"})

# Roles permitted to read upload history (a superset of the upload roles plus
# the read-only operator). Any role NOT in this set has no access at all.
READ_ROLES: frozenset[str] = frozenset({"engineer", "admin", "operator"})

# Wildcard tenant/facility membership (dev-bypass synthetic admin only).
WILDCARD = "*"

_JWT_ALGORITHMS = ["RS256"]


# --------------------------------------------------------------------------- #
# Configuration (read at request time so tests/deployments can flip modes).
# --------------------------------------------------------------------------- #


def _env(name: str, default: str | None = None) -> str | None:
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


def oidc_issuer() -> str | None:
    return _env("WATERTWIN_OIDC_ISSUER")


def oidc_audience() -> str | None:
    return _env("WATERTWIN_OIDC_AUDIENCE")


def oidc_jwks_uri() -> str | None:
    explicit = _env("WATERTWIN_OIDC_JWKS_URI")
    if explicit:
        return explicit
    issuer = oidc_issuer()
    if issuer:
        return issuer.rstrip("/") + "/protocol/openid-connect/certs"
    return None


def oidc_public_key() -> str | None:
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
    subject: str | None = None
    email: str | None = None
    auth_mode: str = "keycloak"
    tenant_id: str = config.DEFAULT_TENANT_ID
    tenants: frozenset[str] = frozenset()

    def has_any(self, *required: str) -> bool:
        return bool(self.roles.intersection(required))

    def can_upload(self) -> bool:
        return self.has_any(*UPLOAD_ROLES)

    def can_read(self) -> bool:
        return self.has_any(*READ_ROLES)

    def can_access_tenant(self, tenant_id: str) -> bool:
        return WILDCARD in self.tenants or tenant_id in self.tenants

    @property
    def actor(self) -> str:
        """Stable identifier recorded in the audit trail for this principal."""
        return self.username or self.subject or "unknown"


# Synthetic principal used only when the dev bypass is active. Carries every
# advisory role and wildcard tenant membership, and is clearly labelled so the
# audit trail never mistakes it for a real Keycloak identity.
SYNTHETIC_ADMIN = Principal(
    username="dev-admin",
    roles=frozenset({"viewer", "operator", "engineer", "admin", "auditor", "security"}),
    subject="dev-admin",
    email=None,
    auth_mode="dev-bypass",
    tenant_id=config.DEFAULT_TENANT_ID,
    tenants=frozenset({WILDCARD}),
)


# --------------------------------------------------------------------------- #
# Token verification (mirrors watertwin-api).
# --------------------------------------------------------------------------- #

_jwks_lock = threading.Lock()
_jwks_client: tuple[str, "jwt.PyJWKClient"] | None = None


def _get_jwks_signing_key(token: str, jwks_uri: str):
    global _jwks_client
    with _jwks_lock:
        if _jwks_client is None or _jwks_client[0] != jwks_uri:
            _jwks_client = (jwks_uri, jwt.PyJWKClient(jwks_uri))
        client = _jwks_client[1]
    return client.get_signing_key_from_jwt(token).key


def _resolve_key(token: str):
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


def _principal_from_claims(claims: dict) -> Principal:
    username = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("sub")
        or "unknown"
    )
    tenants = _string_set_from_claims(claims, "tenant_ids", "tenants", "tenant_id", "tenant")
    if not tenants:
        tenants = frozenset({config.DEFAULT_TENANT_ID})
    # Bind a single tenant at intake: prefer an explicit scalar claim, else the
    # sole membership, else the platform default. Never taken from the body.
    scalar = claims.get("tenant_id") or claims.get("tenant")
    if isinstance(scalar, str) and scalar.strip():
        bound_tenant = scalar.strip()
    elif len(tenants) == 1:
        bound_tenant = next(iter(tenants))
    else:
        bound_tenant = config.DEFAULT_TENANT_ID
    return Principal(
        username=username,
        roles=_roles_from_claims(claims),
        subject=claims.get("sub"),
        email=claims.get("email"),
        auth_mode="keycloak",
        tenant_id=bound_tenant,
        tenants=tenants,
    )


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #

_bearer_scheme = HTTPBearer(auto_error=False, description="Keycloak JWT bearer token")

# The 404 returned to a caller with no ingest access at all. It is deliberately
# identical to a genuine "unknown route" 404 so the surface is not disclosed.
_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> Principal:
    """Resolve the caller's identity (dev bypass -> synthetic admin; else JWT)."""
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


def require_ingest_access(user: Principal = Depends(get_current_user)) -> Principal:
    """Admit only principals with *some* ingest access (read or upload).

    A caller with none (``viewer``, ``security``, or any other role) gets a
    ``404`` on every route, hiding the surface entirely. This dependency is
    attached to the whole ingest router so it runs before any route logic.
    """
    if not user.can_read():
        # Do not leak the difference between "no such route" and "forbidden".
        raise _NOT_FOUND
    return user


def require_upload(user: Principal = Depends(require_ingest_access)) -> Principal:
    """Admit only principals that may upload (``engineer`` / ``admin``).

    A read-only ``operator`` (who has ingest access) is rejected with ``403``:
    the surface exists for them, they simply may not push files.
    """
    if not user.can_upload():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "insufficient role: uploading requires one of "
                f"{sorted(UPLOAD_ROLES)}; caller has {sorted(user.roles)}"
            ),
        )
    return user


def require_admin(user: Principal = Depends(require_ingest_access)) -> Principal:
    """Admit only ``admin`` (used for raw content retrieval)."""
    if not user.has_any("admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient role: this action requires the 'admin' role",
        )
    return user


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
