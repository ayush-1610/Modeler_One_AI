"""Authentication and authorization (task T-06, decision D10).

Keycloak OIDC: the bearer token carries the tenant, the realm roles and the project memberships; an electronic
signature additionally requires a recent step-up (``acr=loa2`` obtained via the signing flow, ``auth_time``
no older than 300 s). Token verification (JWKS, RS256) is injected behind `TokenVerifier`, so the authorization
rules — no token → 401, wrong project → 403, missing/stale step-up → 403 — are tested without a live identity
provider. The real verifier (`JwksTokenVerifier`) validates the signature, issuer and audience against the
realm's JWKS.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, Protocol

from fastapi import Depends, Header, HTTPException

STEP_UP_ACR = "loa2"
STEP_UP_MAX_AGE_S = 300  # D10: auth_time no older than 300 s at signing


class AuthError(Exception):
    """The token is missing, malformed, or fails verification."""


@dataclass(frozen=True)
class Principal:
    user_id: str
    printed_name: str
    tenant_id: str
    roles: frozenset[str]
    projects: frozenset[str]
    acr: str | None
    auth_time: int | None


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    """Map verified OIDC claims to a Principal. The tenant is required; roles/projects default to empty."""
    tenant = claims.get("tenant_id") or claims.get("tenant")
    if not tenant:
        raise AuthError("token carries no tenant claim")
    roles = frozenset((claims.get("realm_access") or {}).get("roles", []))
    projects = frozenset(claims.get("projects", []))
    auth_time = claims.get("auth_time")
    return Principal(
        user_id=str(claims.get("sub", "")),
        printed_name=str(claims.get("name") or claims.get("preferred_username") or claims.get("sub", "")),
        tenant_id=str(tenant),
        roles=roles,
        projects=projects,
        acr=claims.get("acr"),
        auth_time=int(auth_time) if auth_time is not None else None,
    )


class TokenVerifier(Protocol):
    """Verifies a bearer token's signature/issuer/audience and returns its claims; raises AuthError otherwise."""

    def verify(self, token: str) -> dict[str, Any]: ...


class JwksTokenVerifier:
    """Verifies RS256 tokens against the Keycloak realm's JWKS (keys cached), checking issuer and audience."""

    def __init__(self, *, jwks_url: str, issuer: str, audience: str):
        import jwt

        self._client = jwt.PyJWKClient(jwks_url)
        self._issuer = issuer
        self._audience = audience

    def verify(self, token: str) -> dict[str, Any]:
        import jwt

        try:
            key = self._client.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token, key, algorithms=["RS256"], issuer=self._issuer, audience=self._audience,
                options={"require": ["exp", "iat"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"token rejected: {exc}") from exc


@lru_cache
def _configured_verifier() -> TokenVerifier | None:
    from modeler_api.config import get_settings

    settings = get_settings()
    if not settings.oidc_jwks_url or not settings.oidc_issuer:
        return None
    return JwksTokenVerifier(jwks_url=settings.oidc_jwks_url, issuer=settings.oidc_issuer, audience=settings.oidc_audience)


def get_verifier() -> TokenVerifier:
    verifier = _configured_verifier()
    if verifier is None:
        raise HTTPException(status_code=503, detail="Authentication is not configured (Keycloak / JWKS).")
    return verifier


def current_principal(
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Require and verify a bearer token; 401 when it is missing or invalid."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    token = authorization.split(" ", 1)[1].strip()
    try:
        return principal_from_claims(verifier.verify(token))
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require_role(*roles: str):
    """Dependency: the principal must hold at least one of `roles` (else 403)."""

    def dependency(principal: CurrentPrincipal) -> Principal:
        if not set(roles) & principal.roles:
            raise HTTPException(status_code=403, detail=f"requires realm role {' or '.join(roles)}")
        return principal

    return dependency


def require_project(project_id: str, principal: Principal) -> None:
    """403 unless the principal is a member of `project_id`."""
    if project_id not in principal.projects:
        raise HTTPException(status_code=403, detail=f"not a member of project {project_id}")


def ensure_step_up(principal: Principal, *, now: float | None = None) -> None:
    """403 unless the token proves a recent step-up (acr=loa2 and auth_time within 300 s)."""
    if principal.acr != STEP_UP_ACR:
        raise HTTPException(status_code=403, detail={"code": "STEP_UP_REQUIRED", "message": "a loa2 step-up is required to sign"})
    current = time.time() if now is None else now
    if principal.auth_time is None or current - principal.auth_time > STEP_UP_MAX_AGE_S:
        raise HTTPException(status_code=403, detail={"code": "STEP_UP_STALE", "message": "re-authenticate: the step-up is older than 300 s"})
