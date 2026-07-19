"""
Verifies JWTs issued by auth-service using the shared JWT_SECRET_KEY. This
is now the FOURTH service with an near-identical copy of this module
(auth-service issues; inventory-service, sales-service, and now
payment-service all verify the same way). Three occurrences was already
flagged as worth extracting into packages/auth in docs/PHASES.md; four
is past the point where "wait for a clean moment" is a reasonable excuse
— this should be the first thing done at the start of the next phase,
before writing a fifth copy.

Webhook routes (app/api/v1/webhook_routes.py) do NOT use any of this —
providers call those endpoints directly, with no JWT at all. Signature
verification there is provider-specific (HMAC per adapter), not the
platform's own auth.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from shopflow_constants import Permission

from app.core.config import get_settings

_bearer_scheme = HTTPBearer(auto_error=False)


class Principal:
    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        business_id: uuid.UUID | None,
        role: str,
        permissions: list[str],
    ):
        self.user_id = user_id
        self.business_id = business_id
        self.role = role
        self.permissions = frozenset(permissions)

    def has_permission(self, permission: Permission) -> bool:
        return permission.value in self.permissions


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> Principal:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc

    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token is not an access token")

    business_id_raw = payload.get("business_id")
    return Principal(
        user_id=uuid.UUID(payload["sub"]),
        business_id=uuid.UUID(business_id_raw) if business_id_raw else None,
        role=payload["role"],
        permissions=payload.get("permissions", []),
    )


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_permission(permission: Permission):
    async def _check(principal: CurrentPrincipal) -> Principal:
        if not principal.has_permission(permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission.value}",
            )
        return principal

    return _check


async def require_business_context(principal: CurrentPrincipal) -> uuid.UUID:
    if principal.business_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="This operation requires an authenticated business context",
        )
    return principal.business_id


BusinessContext = Annotated[uuid.UUID, Depends(require_business_context)]
