from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class RestockRequest(BaseModel):
    product_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal = Field(..., gt=0)
    reference_id: uuid.UUID | None = None


class SaleRequest(BaseModel):
    product_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal = Field(..., gt=0)
    reference_id: uuid.UUID | None = None


class AdjustmentRequest(BaseModel):
    product_id: uuid.UUID
    location_id: uuid.UUID
    quantity_delta: Decimal
    reason: str = Field(..., min_length=1)


class WasteRequest(BaseModel):
    product_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal = Field(..., gt=0)
    reason: str = Field(..., min_length=1)


class TransferRequest(BaseModel):
    product_id: uuid.UUID
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID
    quantity: Decimal = Field(..., gt=0)


class ReturnRequest(BaseModel):
    product_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal = Field(..., gt=0)
    reference_id: uuid.UUID | None = None
    reason: str | None = None


class BatchStockItemRequest(BaseModel):
    product_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal = Field(..., gt=0)


class BatchSaleRequest(BaseModel):
    items: list[BatchStockItemRequest] = Field(..., min_length=1, max_length=200)
    reference_id: uuid.UUID | None = None


class BatchReturnRequest(BaseModel):
    items: list[BatchStockItemRequest] = Field(..., min_length=1, max_length=200)
    reference_id: uuid.UUID | None = None
    reason: str | None = None


class StockMovementResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    location_id: uuid.UUID
    movement_type: str
    quantity_delta: Decimal
    resulting_quantity: Decimal
    reference_type: str | None
    reference_id: uuid.UUID | None
    reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class StockLevelResponse(BaseModel):
    product_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal


class LowStockItemResponse(BaseModel):
    product_id: uuid.UUID
    product_name: str
    sku: str
    location_id: uuid.UUID
    current_quantity: Decimal
    low_stock_threshold: Decimal
