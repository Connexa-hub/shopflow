"""Declarative base for payment-service — fresh isolated metadata via
create_base(). See packages/database's base.py for why a shared Base
instance across services would be wrong."""
from shopflow_database import TimestampMixin, UUIDPrimaryKeyMixin, create_base

Base = create_base()

__all__ = ["Base", "TimestampMixin", "UUIDPrimaryKeyMixin"]
