"""
Sales domain models.

No `relationship()` declarations here, same reasoning as inventory-service
(see that service's models.py): async SQLAlchemy raises MissingGreenlet on
an unloaded lazy relationship access unless every call site remembers to
eager-load, so repositories join explicitly instead and this file stays
plain FK columns.

Snapshotting: SaleItem stores `sku`, `product_name`, and `unit_price` as
they were AT THE TIME OF SALE, not a live reference to inventory-service's
current product data. A receipt printed a year from now must show what was
actually sold, even if the product was renamed, repriced, or deleted since.
This is the same reasoning e-commerce order-line-items use industry-wide.

`product_id` itself is still stored, but only as a reference for cross-
service lookups (e.g. "show me this sale's product in the catalog") — it
is NEVER used to re-fetch current price/name for display purposes.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from shopflow_database import tenant_id_column

from app.domain.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SaleStatus(str, enum.Enum):
    COMPLETED = "completed"
    VOIDED = "voided"


class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    CARD = "card"
    MOBILE_MONEY = "mobile_money"
    BANK_TRANSFER = "bank_transfer"
    CREDIT = "credit"  # unpaid balance — the customer now owes the business
    WALLET = "wallet"  # future customer wallet (Phase 7+), accepted as a
    # valid enum value now so payment records written today don't need a
    # migration when that feature ships.


class Sale(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sales"

    business_id: Mapped[uuid.UUID] = tenant_id_column()
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    cashier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)

    receipt_number: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default=SaleStatus.COMPLETED.value)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    balance_due: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))

    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SaleItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sale_items"

    sale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id"), index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)

    # Snapshotted at time of sale — see module docstring.
    sku: Mapped[str] = mapped_column(String(64))
    product_name: Mapped[str] = mapped_column(String(255))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class SalePayment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sale_payments"

    sale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id"), index=True
    )
    method: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ReceiptCounter(Base, TimestampMixin):
    """One row per business, atomically incremented to produce sequential,
    human-readable receipt numbers ('RCP-000123') instead of a raw UUID on
    every receipt. Deliberately NOT UUIDPrimaryKeyMixin — business_id
    itself is the primary key, one counter per tenant."""

    __tablename__ = "receipt_counters"

    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, default=0)
