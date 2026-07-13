"""initial schema: sales, sale_items, sale_payments, receipt_counters

Revision ID: 0001
Revises:
Create Date: 2026-07-12
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
        "sales",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cashier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("receipt_number", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("discount_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("amount_paid", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("balance_due", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sales_business_id", "sales", ["business_id"])
    op.create_index("ix_sales_location_id", "sales", ["location_id"])
    op.create_index("ix_sales_customer_id", "sales", ["customer_id"])
    op.create_index("ix_sales_cashier_id", "sales", ["cashier_id"])
    op.create_index("ix_sales_receipt_number", "sales", ["receipt_number"])

    op.create_table(
        "sale_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "sale_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales.id"), nullable=False
        ),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sale_items_sale_id", "sale_items", ["sale_id"])
    op.create_index("ix_sale_items_product_id", "sale_items", ["product_id"])

    op.create_table(
        "sale_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "sale_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales.id"), nullable=False
        ),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("reference", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sale_payments_sale_id", "sale_payments", ["sale_id"])

    op.create_table(
        "receipt_counters",
        sa.Column("business_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("last_number", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("receipt_counters")
    op.drop_table("sale_payments")
    op.drop_table("sale_items")
    op.drop_table("sales")
