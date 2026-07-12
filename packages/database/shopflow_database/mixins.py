"""
Shared SQLAlchemy declarative base and mixins.

Every service gets its own Base() instance (SQLAlchemy does not support
sharing a single metadata object cleanly across independently-migrated
services), but they all inherit the SAME mixins from here — so a
`business_id` column, a timestamp pair, or a soft-delete flag behaves
identically everywhere, and a bugfix here doesn't require hunting down
copies in ten services.

Why each service still gets its own Base subclass: services own their own
Alembic migration history and their own tables. Sharing one Base/metadata
object across services would mean inventory-service's migrations could
accidentally see (and try to manage) auth-service's tables. Composition via
mixins gives us shared behavior without shared ownership.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPrimaryKeyMixin:
    """Every table gets a UUID primary key, never an auto-increment int.

    Why: auto-increment IDs leak information (row count, creation order)
    across tenant boundaries and make client-generated IDs (needed for
    offline-first writes — see sync-service, Phase 5) impossible. UUIDs can
    be generated on a merchant's phone while offline and never collide when
    synced later.
    """

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SoftDeleteMixin:
    """Commerce data is never hard-deleted. A deleted product might still
    be referenced by a historical sale; a hard DELETE would corrupt
    reporting and receipts for past transactions."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


def tenant_id_column():
    """Factory for a `business_id` column, consistent across every service.

    Deliberately NOT a real ForeignKey to `businesses.id` — that table lives
    in auth-service's own database/schema. In this architecture each service
    owns its own database (no cross-service DB access, per the repo README),
    so `business_id` is validated by the service layer against the caller's
    JWT claims, not by a Postgres FK constraint. This function just keeps the
    column *type* and *nullability* consistent everywhere; add an index by
    default since every tenant-scoped query filters on this column.
    """
    return mapped_column(UUID(as_uuid=True), nullable=False, index=True)
