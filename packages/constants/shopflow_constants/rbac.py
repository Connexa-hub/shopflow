"""
Single source of truth for roles and permissions across ShopFlow services.

Downstream services never hardcode role strings — they import from here so
a role rename or new permission is a one-file change, not a grep-and-replace
across ten repos.
"""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    PLATFORM_OWNER = "platform_owner"   # Anthropic-style "superadmin" — runs the platform
    BUSINESS_OWNER = "business_owner"   # Owns one or more businesses/branches
    MANAGER = "manager"                 # Manages a single branch
    CASHIER = "cashier"                 # POS operations only
    STAFF = "staff"                     # Limited, task-specific access


class Permission(str, Enum):
    # Inventory
    INVENTORY_READ = "inventory:read"
    INVENTORY_WRITE = "inventory:write"
    INVENTORY_DELETE = "inventory:delete"

    # Sales / POS
    SALES_CREATE = "sales:create"
    SALES_REFUND = "sales:refund"
    SALES_READ = "sales:read"

    # Staff management
    STAFF_INVITE = "staff:invite"
    STAFF_REMOVE = "staff:remove"
    STAFF_READ = "staff:read"

    # Business configuration / branding
    BUSINESS_CONFIGURE = "business:configure"

    # Financial
    EXPENSES_WRITE = "expenses:write"
    REPORTS_READ = "reports:read"

    # Platform-level (platform_owner only)
    PLATFORM_MANAGE_MERCHANTS = "platform:manage_merchants"
    PLATFORM_MANAGE_FEATURE_FLAGS = "platform:manage_feature_flags"


# Default permission grants per role. Businesses can layer custom
# role/permission overrides on top of this later (franchise requirement) —
# this table is the seed, not a hard ceiling enforced in the DB schema.
DEFAULT_ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.PLATFORM_OWNER: frozenset(Permission),  # everything
    Role.BUSINESS_OWNER: frozenset(
        {
            Permission.INVENTORY_READ,
            Permission.INVENTORY_WRITE,
            Permission.INVENTORY_DELETE,
            Permission.SALES_CREATE,
            Permission.SALES_REFUND,
            Permission.SALES_READ,
            Permission.STAFF_INVITE,
            Permission.STAFF_REMOVE,
            Permission.STAFF_READ,
            Permission.BUSINESS_CONFIGURE,
            Permission.EXPENSES_WRITE,
            Permission.REPORTS_READ,
        }
    ),
    Role.MANAGER: frozenset(
        {
            Permission.INVENTORY_READ,
            Permission.INVENTORY_WRITE,
            Permission.SALES_CREATE,
            Permission.SALES_REFUND,
            Permission.SALES_READ,
            Permission.STAFF_READ,
            Permission.EXPENSES_WRITE,
            Permission.REPORTS_READ,
        }
    ),
    Role.CASHIER: frozenset(
        {
            Permission.INVENTORY_READ,
            Permission.SALES_CREATE,
            Permission.SALES_READ,
        }
    ),
    Role.STAFF: frozenset(
        {
            Permission.INVENTORY_READ,
        }
    ),
}
