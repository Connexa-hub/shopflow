"""
Shared JWT verification and RBAC dependency factories.

Extracted after the third near-identical copy of this module appeared
across inventory-service, sales-service, and payment-service (see
docs/PHASES.md's Phase 4 notes) — auth-service issues tokens and has its
own, structurally different security.py for hashing/issuance, so it has
no need of this module.

Why factories, not a shared Settings instance: every service has its OWN
Settings class (inheriting jwt_secret_key/jwt_algorithm from
packages/configuration's BaseServiceSettings) and its own get_settings().
There is no single shared settings object to import here — instead, each
service calls create_principal_dependency(get_settings) once, passing its
OWN get_settings function, and gets back a dependency bound to its own
configuration. This mirrors the same reasoning packages/database's
create_base() factory uses for the same underlying issue (no shared state
that would let one service's config leak into another's).

Usage in a service's own app/core/security.py (which becomes a thin
wiring file, not a reimplementation):

    from shopflow_auth import (
        Principal, create_principal_dependency,
        create_permission_checker, create_business_context_dependency,
    )
    from app.core.config import get_settings

    get_current_principal = create_principal_dependency(get_settings)
    CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]

    def require_permission(permission):
        return create_permission_checker(get_current_principal, permission)

    require_business_context = create_business_context_dependency(get_current_principal)
    BusinessContext = Annotated[uuid.UUID, Depends(require_business_context)]
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any, Callable, Protocol

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from shopflow_constants import Permission

_bearer_scheme = HTTPBearer(auto_error=False)


class HasJWTConfig(Protocol):
    """The minimum shape create_principal_dependency needs from a
    service's Settings object — every BaseServiceSettings subclass
    satisfies this structurally, without needing to import
    shopflow_configuration here (that would make this package depend on
    configuration for a two-field shape check, which isn't worth the
    coupling)."""

    jwt_secret_key: str
    jwt_algorithm: str


class Principal:
    """The authenticated caller, decoded from their JWT access token.

    `raw_token` is optional and only populated/used by services that need
    to forward the caller's own token to another service (sales-service
    calling inventory-service, for instance) — most services never touch
    it."""

    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        business_id: uuid.UUID | None,
        role: str,
        permissions: list[str],
        raw_token: str | None = None,
    ):
        self.user_id = user_id
        self.business_id = business_id
        self.role = role
        self.permissions = frozenset(permissions)
        self.raw_token = raw_token

    def has_permission(self, permission: Permission) -> bool:
        return permission.value in self.permissions


def create_principal_dependency(
    get_settings: Callable[[], HasJWTConfig],
) -> Callable[..., Any]:
    """Returns a FastAPI dependency function bound to one service's own
    settings accessor. Call once per service, at import time, and reuse
    the returned callable — do not call this factory again per-request."""

    async def get_current_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    ) -> Principal:
        if credentials is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

        settings = get_settings()
        try:
            payload = jwt.decode(
                credentials.credentials, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
            )
        except JWTError as exc:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
            ) from exc

        if payload.get("type") != "access":
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, detail="Token is not an access token"
            )

        business_id_raw = payload.get("business_id")
        return Principal(
            user_id=uuid.UUID(payload["sub"]),
            business_id=uuid.UUID(business_id_raw) if business_id_raw else None,
            role=payload["role"],
            permissions=payload.get("permissions", []),
            raw_token=credentials.credentials,
        )

    return get_current_principal


def create_permission_checker(
    get_current_principal: Callable[..., Any], permission: Permission
) -> Callable[..., Any]:
    """Returns a FastAPI dependency enforcing `permission`, built on top
    of a service's own get_current_principal dependency (from
    create_principal_dependency). Usage:
    `Depends(create_permission_checker(get_current_principal, Permission.SALES_CREATE))`,
    or more commonly wrapped in a per-service `require_permission(permission)`
    helper — see this module's docstring."""

    async def _check(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        if not principal.has_permission(permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission.value}",
            )
        return principal

    return _check


def create_business_context_dependency(
    get_current_principal: Callable[..., Any],
) -> Callable[..., Any]:
    """Returns a FastAPI dependency extracting business_id, rejecting
    principals with no business context (platform_owner) explicitly
    rather than letting a None flow silently into a repository filter."""

    async def _require_business_context(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> uuid.UUID:
        if principal.business_id is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="This operation requires an authenticated business context",
            )
        return principal.business_id

    return _require_business_context
