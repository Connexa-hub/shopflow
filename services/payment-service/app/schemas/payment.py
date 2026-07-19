from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

from app.domain.models import PaymentProvider, PaymentPurpose, PaymentStatus


class InitializePaymentRequest(BaseModel):
    provider: PaymentProvider
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(default="NGN", min_length=3, max_length=8)
    customer_email: EmailStr
    purpose: PaymentPurpose
    related_sale_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    metadata: dict = Field(default_factory=dict)


class PaymentTransactionResponse(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    provider: PaymentProvider
    status: PaymentStatus
    purpose: PaymentPurpose
    internal_reference: str
    provider_reference: str | None
    amount: Decimal
    currency: str
    customer_email: str
    customer_id: uuid.UUID | None
    related_sale_id: uuid.UUID | None
    checkout_url: str | None
    verified_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
