"""Declarative base for sales-service — see packages/database's base.py for
why this must be a freshly-created Base per service (isolated MetaData),
not a shared instance."""
from shopflow_database import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, create_base

Base = create_base()

__all__ = ["Base", "TimestampMixin", "UUIDPrimaryKeyMixin", "SoftDeleteMixin"]
