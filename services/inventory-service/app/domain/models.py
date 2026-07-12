"""
Inventory domain models.

Critical invariant: `StockLevel.quantity` is a CACHED, DERIVED value. It
must never be written directly — every change goes through
StockService.record_movement(), which writes an immutable StockMovement
row FIRST and derives the new cached quantity from it. This is what lets a
shop owner answer "what happened to this stock" after the fact; a raw
`UPDATE products SET quantity = quantity - 1` can never answer that.

No `relationship()` declarations on purpose: in async SQLAlchemy, lazily
accessing an unloaded relationship attribute raises MissingGreenlet unless
the query explicitly eager-loaded it. Repositories in this service always
join explicitly and select the columns they need instead — fewer footguns,
easier to reason about, and every query's cost is visible at the call site.
"""
from __future__ import annotations

import enum
import uuid
from decimal import Decimal

from shopflow_database import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, tenant_id_column
from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class MovementType(str, enum.Enum):
    INITIAL = "initial"
    RESTOCK = "restock"
    SALE = "sale"
    ADJUSTMENT = "adjustment"
    WASTE = "waste"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    RETURN = "return"


class Location(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A physical branch/store. Every business has at least one, created
    automatically as 'Main Store' when the business registers (Phase 3+
    wiring — for now, created explicitly via the API)."""

    __tablename__ = "locations"

    business_id: Mapped[uuid.UUID] = tenant_id_column()
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Category(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "categories"

    business_id: Mapped[uuid.UUID] = tenant_id_column()
    name: Mapped[str] = mapped_column(String(255))
    # Self-referential FK for nested categories (e.g. "Beverages" > "Soft
    # Drinks"). Nullable = top-level category. No recursive query support
    # yet — column exists now so the schema doesn't need a breaking
    # migration when nested category UI lands later.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )


class Supplier(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "suppliers"

    business_id: Mapped[uuid.UUID] = tenant_id_column()
    name: Mapped[str] = mapped_column(String(255))
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)


class Product(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "products"
    __table_args__ = (
        # Scoped to (business_id, sku) — NOT a global unique constraint.
        # Two different merchants both using "SKU-001" is normal and must
        # never collide; this is the tenant-isolation test worth trusting.
        UniqueConstraint("business_id", "sku", name="uq_products_business_sku"),
        UniqueConstraint("business_id", "barcode", name="uq_products_business_barcode"),
    )

    business_id: Mapped[uuid.UUID] = tenant_id_column()
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True
    )

    sku: Mapped[str] = mapped_column(String(64))
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Free-text unit ("piece", "kg", "carton", "yard"...) rather than an
    # enum — units vary too much across provision stores, pharmacies, and
    # market traders to enumerate up front.
    unit: Mapped[str] = mapped_column(String(32), default="piece")

    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Numeric, not Integer: loose goods (rice, fabric, produce) are sold
    # and stocked in fractional quantities.
    low_stock_threshold: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class StockLevel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Cached current quantity for one product at one location. Derived —
    see module docstring. Updated only via an atomic SQL UPDATE
    (quantity = quantity + delta), which stays correct under concurrent
    writes on any backend without needing dialect-specific row locking."""

    __tablename__ = "stock_levels"
    __table_args__ = (
        UniqueConstraint("product_id", "location_id", name="uq_stock_levels_product_location"),
    )

    business_id: Mapped[uuid.UUID] = tenant_id_column()
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))


class StockMovement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only audit ledger. Every stock change, ever, forever. Never
    updated, never deleted. `resulting_quantity` snapshots the balance
    immediately after this movement — like a bank statement line — so
    reconciliation never needs to replay the whole history."""

    __tablename__ = "stock_movements"

    business_id: Mapped[uuid.UUID] = tenant_id_column()
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), index=True
    )

    movement_type: Mapped[str] = mapped_column(String(32))
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    resulting_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))

    # Loosely links back to the originating record (a sale, a transfer
    # pair, a purchase order) without a hard FK — the originating table
    # lives in a different service's database (sales-service, Phase 3),
    # and cross-service FKs aren't possible in a per-service-database
    # architecture.
    reference_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
