"""
Declarative base and shared mixins for auth-service models.

These are re-exported from the shared `shopflow_database` package (see
packages/database) rather than defined here — this used to be a local
definition duplicated per-service; Phase 2 extracted it to one place so a
fix or new mixin (e.g. SoftDeleteMixin) doesn't need to be copy-pasted into
every future service. `Base` itself is created fresh via `create_base()`
so auth-service's MetaData/migration history stays fully isolated from
every other service's, per shopflow_database's design (see its base.py
docstring for why a shared Base instance would be wrong).
"""
from shopflow_database import TimestampMixin, UUIDPrimaryKeyMixin, create_base

Base = create_base()

__all__ = ["Base", "TimestampMixin", "UUIDPrimaryKeyMixin"]
