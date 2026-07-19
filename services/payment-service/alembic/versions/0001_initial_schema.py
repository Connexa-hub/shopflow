"""initial schema: payment_transactions, webhook_events

Revision ID: 0001
Revises:
Create Date: 2026-07-14
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("internal_reference", sa.String(100), nullable=False),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="NGN"),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("related_sale_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("checkout_url", sa.String(1000), nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "internal_reference", name="uq_payment_transactions_internal_reference"
        ),
    )
    op.create_index("ix_payment_transactions_business_id", "payment_transactions", ["business_id"])
    op.create_index("ix_payment_transactions_provider", "payment_transactions", ["provider"])
    op.create_index("ix_payment_transactions_status", "payment_transactions", ["status"])
    op.create_index(
        "ix_payment_transactions_internal_reference", "payment_transactions", ["internal_reference"]
    )
    op.create_index(
        "ix_payment_transactions_provider_reference", "payment_transactions", ["provider_reference"]
    )

    op.create_table(
        "webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_key", sa.String(255), nullable=False),
        sa.Column("internal_reference", sa.String(100), nullable=True),
        sa.Column("raw_payload", sa.Text, nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider", "provider_event_key", name="uq_webhook_events_provider_event_key"
        ),
    )
    op.create_index("ix_webhook_events_provider", "webhook_events", ["provider"])
    op.create_index("ix_webhook_events_internal_reference", "webhook_events", ["internal_reference"])


def downgrade() -> None:
    op.drop_table("webhook_events")
    op.drop_table("payment_transactions")
