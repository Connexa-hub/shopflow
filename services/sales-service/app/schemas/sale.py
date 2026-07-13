from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.domain.models import PaymentMethod, SaleStatus


class SaleItemRequest(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(..., gt=0)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)


class SalePaymentRequest(BaseModel):
    method: PaymentMethod
    amount: Decimal = Field(..., gt=0)
    reference: str | None = Field(default=None, max_length=255)


class CreateSaleRequest(BaseModel):
    location_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    items: list[SaleItemRequest] = Field(..., min_length=1, max_length=200)
    payments: list[SalePaymentRequest] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _no_duplicate_products(self) -> "CreateSaleRequest":
        product_ids = [item.product_id for item in self.items]
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("Duplicate product_id in items — combine into one line item")
        return self


class VoidSaleRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class SaleItemResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    unit_price: Decimal
    quantity: Decimal
    discount_amount: Decimal
    line_total: Decimal

    model_config = {"from_attributes": True}


class SalePaymentResponse(BaseModel):
    id: uuid.UUID
    method: str
    amount: Decimal
    reference: str | None

    model_config = {"from_attributes": True}


class SaleResponse(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    location_id: uuid.UUID
    customer_id: uuid.UUID | None
    cashier_id: uuid.UUID
    receipt_number: str
    status: SaleStatus
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    voided_at: datetime | None
    void_reason: str | None
    created_at: datetime
    items: list[SaleItemResponse] = []
    payments: list[SalePaymentResponse] = []

    model_config = {"from_attributes": True}
