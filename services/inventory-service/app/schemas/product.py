from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class CreateProductRequest(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64)
    barcode: str | None = Field(default=None, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    unit: str = Field(default="piece", max_length=32)
    cost_price: Decimal = Field(default=Decimal("0"), ge=0)
    unit_price: Decimal = Field(..., ge=0)
    low_stock_threshold: Decimal = Field(default=Decimal("0"), ge=0)
    category_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None


class UpdateProductRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    barcode: str | None = None
    description: str | None = None
    unit: str | None = None
    cost_price: Decimal | None = Field(default=None, ge=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    low_stock_threshold: Decimal | None = Field(default=None, ge=0)
    category_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    is_active: bool | None = None


class BatchProductLookupRequest(BaseModel):
    product_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=200)


class ProductResponse(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    sku: str
    barcode: str | None
    name: str
    description: str | None
    unit: str
    cost_price: Decimal
    unit_price: Decimal
    low_stock_threshold: Decimal
    category_id: uuid.UUID | None
    supplier_id: uuid.UUID | None
    is_active: bool

    model_config = {"from_attributes": True}
