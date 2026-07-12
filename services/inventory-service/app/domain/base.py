"""
inventory-service's own isolated declarative Base and re-exported mixins.
See packages/database's base.py docstring for why this must be a fresh
`create_base()` call per service rather than a shared imported instance.
"""
from shopflow_database import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, create_base

Base = create_base()

__all__ = ["Base", "TimestampMixin", "UUIDPrimaryKeyMixin", "SoftDeleteMixin"]
