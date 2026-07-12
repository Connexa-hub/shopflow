from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class CreateCategoryRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: uuid.UUID | None = None


class CategoryResponse(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class CreateLocationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    address: str | None = None
    is_primary: bool = False


class LocationResponse(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    address: str | None
    is_primary: bool
    is_active: bool

    model_config = {"from_attributes": True}


class CreateSupplierRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    phone_number: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    address: str | None = None


class SupplierResponse(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    phone_number: str | None
    email: str | None
    address: str | None

    model_config = {"from_attributes": True}
