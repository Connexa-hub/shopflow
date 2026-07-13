"""
Verifies JWTs issued by auth-service using the shared JWT_SECRET_KEY. Same
pattern as inventory-service's app/core/security.py — this is now the
THIRD service with an identical copy of this ~50-line module (auth-service
issues tokens; inventory-service and sales-service both verify them the
same way). Worth extracting into packages/auth now that a third occurrence
confirms the pattern is stable — flagged in docs/PHASES.md as a follow-up
rather than done as an unplanned mid-phase refactor of an already-shipped,
green service.

One addition inventory-service didn't need: `Principal.raw_token`. Unlike
inventory-service (which only ever receives calls, never makes them),
sales-service is a CALLER too — it forwards the cashier's own token to
inventory-service (see app/core/inventory_client.py), so the raw token
string has to survive alongside the decoded claims.
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
    """The authenticated caller, decoded from their JWT access token."""

    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        business_id: uuid.UUID | None,
        role: str,
        permissions: list[str],
        raw_token: str,
    ):
        self.user_id = user_id
        self.business_id = business_id
        self.role = role
        self.permissions = frozenset(permissions)
        self.raw_token = raw_token

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
        raw_token=credentials.credentials,
    )


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_permission(permission: Permission):
    """FastAPI dependency factory, e.g.:
    `Depends(require_permission(Permission.SALES_CREATE))`
    """

    async def _check(principal: CurrentPrincipal) -> Principal:
        if not principal.has_permission(permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission.value}",
            )
        return principal

    return _check


async def require_business_context(principal: CurrentPrincipal) -> uuid.UUID:
    """Nearly every sales endpoint scopes its query by business_id. See
    inventory-service's identical dependency for why platform_owner
    (business_id=None) is rejected explicitly here rather than letting a
    None flow silently into a repository filter."""
    if principal.business_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="This operation requires an authenticated business context",
        )
    return principal.business_id


BusinessContext = Annotated[uuid.UUID, Depends(require_business_context)]
