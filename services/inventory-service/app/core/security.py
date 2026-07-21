"""
Thin per-service wiring around packages/auth's shared JWT verification and
RBAC dependency factories. The actual logic lives in
packages/auth/shopflow_auth/security.py — this file only binds it to
inventory-service's own Settings/get_settings, and re-exports the same
names every route file already imports (Principal, BusinessContext,
require_permission) so no route file needed to change.
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
