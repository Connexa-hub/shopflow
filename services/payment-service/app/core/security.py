"""
Thin per-service wiring around packages/auth's shared JWT verification and
RBAC dependency factories. See packages/auth/shopflow_auth/security.py for
the actual logic.

Not used by app/api/v1/webhook_routes.py — providers call those directly
with no bearer token at all; see that module's docstring.
"""
import uuid
from typing import Annotated

from fastapi import Depends
from shopflow_auth import (
    Principal,
    create_business_context_dependency,
    create_permission_checker,
    create_principal_dependency,
)
from shopflow_constants import Permission

from app.core.config import get_settings

get_current_principal = create_principal_dependency(get_settings)
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_permission(permission: Permission):
    return create_permission_checker(get_current_principal, permission)


require_business_context = create_business_context_dependency(get_current_principal)
BusinessContext = Annotated[uuid.UUID, Depends(require_business_context)]

__all__ = [
    "Principal",
    "get_current_principal",
    "CurrentPrincipal",
    "require_permission",
    "require_business_context",
    "BusinessContext",
]
