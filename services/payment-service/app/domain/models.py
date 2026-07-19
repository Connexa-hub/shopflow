"""
Payment domain models.

Provider adapters (app/providers/) never touch these models directly —
PaymentService is the only layer that reads/writes them, same repository-
pattern separation used throughout the platform. No `relationship()`
declarations, same reasoning as every other service: async SQLAlchemy
raises MissingGreenlet on an unloaded lazy relationship access, so
repositories join explicitly instead where needed.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from shopflow_database import tenant_id_column

from app.domain.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PaymentProvider(str, enum.Enum):
    PAYSTACK = "paystack"
    FLUTTERWAVE = "flutterwave"
    MONNIFY = "monnify"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    ABANDONED = "abandoned"


class PaymentPurpose(str, enum.Enum):
    """Deliberately generic rather than sales-only — payment-service exists
    for PROVIDER-MEDIATED payments (online checkout links, wallet top-ups,
    invoice payments), which is a different concern from sales-service's
    SalePayment.method (cash/card/credit recorded directly at the POS,
    settled via physical hardware, no provider API involved). A sale paid
    for online would use purpose=SALE_PAYMENT with related_sale_id set;
    the other purposes exist for features later phases will build."""

    SALE_PAYMENT = "sale_payment"
    WALLET_TOPUP = "wallet_topup"
    INVOICE = "invoice"


class PaymentTransaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "payment_transactions"
    __table_args__ = (
        UniqueConstraint("internal_reference", name="uq_payment_transactions_internal_reference"),
    )

    business_id: Mapped[uuid.UUID] = tenant_id_column()
    provider: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default=PaymentStatus.PENDING.value, index=True)
    purpose: Mapped[str] = mapped_column(String(32))

    # Our own reference, generated before ever calling the provider — this
    # is what we use as the idempotency key end-to-end, and what we hand
    # the provider as *their* reference field (tx_ref / reference /
    # paymentReference) so a provider-side lookup and a local lookup always
    # agree on the same string.
    internal_reference: Mapped[str] = mapped_column(String(100), index=True)

    # The provider's OWN transaction identifier, which may differ from
    # internal_reference (e.g. Paystack returns a separate "reference" that
    # usually echoes ours, but Flutterwave/Monnify return their own numeric
    # or prefixed transaction id as the authoritative handle for verify
    # calls) — populated once we get a response back.
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(8), default="NGN")

    customer_email: Mapped[str] = mapped_column(String(255))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    related_sale_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    checkout_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class WebhookEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only log of every webhook received, keyed by provider +
    their event/transaction identifier, so a retried webhook (all three
    providers explicitly retry on non-200 responses, and can even send
    legitimate duplicates) can be recognized and skipped rather than
    reprocessed. This is the idempotency mechanism, not a side effect of
    checking PaymentTransaction.status alone — a duplicate webhook for an
    already-successful transaction should still be acknowledged with 200
    (so the provider stops retrying) without re-running any side effects."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_event_key", name="uq_webhook_events_provider_event_key"
        ),
    )

    provider: Mapped[str] = mapped_column(String(32), index=True)
    # Provider's event/webhook id if they send one (Flutterwave does: the
    # top-level `id` field), otherwise falls back to a hash of the raw
    # payload — either way, a stable key to detect an exact-duplicate
    # delivery of the same event.
    provider_event_key: Mapped[str] = mapped_column(String(255))
    internal_reference: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    raw_payload: Mapped[str] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
