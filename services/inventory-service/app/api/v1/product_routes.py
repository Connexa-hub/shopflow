import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from shopflow_constants import Permission

from app.core.dependencies import ProductServiceDep
from app.core.security import BusinessContext, Principal, require_permission
from app.schemas.product import CreateProductRequest, ProductResponse, UpdateProductRequest
from app.services.product_service import (
    DuplicateBarcodeError,
    DuplicateSKUError,
    InvalidProductReferenceError,
    ProductNotFoundError,
)

router = APIRouter(prefix="/api/v1/products", tags=["products"])

CanReadInventory = Annotated[Principal, Depends(require_permission(Permission.INVENTORY_READ))]
CanWriteInventory = Annotated[Principal, Depends(require_permission(Permission.INVENTORY_WRITE))]


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: CreateProductRequest,
    business_id: BusinessContext,
    product_service: ProductServiceDep,
    _principal: CanWriteInventory,
) -> ProductResponse:
    try:
        product = await product_service.create_product(business_id=business_id, **body.model_dump())
    except DuplicateSKUError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DuplicateBarcodeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidProductReferenceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ProductResponse.model_validate(product)


@router.get("/barcode/{barcode}", response_model=ProductResponse)
async def get_product_by_barcode(
    barcode: str,
    business_id: BusinessContext,
    product_service: ProductServiceDep,
    _principal: CanReadInventory,
) -> ProductResponse:
    try:
        product = await product_service.get_by_barcode(business_id=business_id, barcode=barcode)
    except ProductNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ProductResponse.model_validate(product)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    business_id: BusinessContext,
    product_service: ProductServiceDep,
    _principal: CanReadInventory,
) -> ProductResponse:
    try:
        product = await product_service.get_product(business_id=business_id, product_id=product_id)
    except ProductNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ProductResponse.model_validate(product)


@router.get("", response_model=list[ProductResponse])
async def list_products(
    business_id: BusinessContext,
    product_service: ProductServiceDep,
    _principal: CanReadInventory,
    category_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ProductResponse]:
    products = await product_service.list_products(
        business_id=business_id,
        category_id=category_id,
        is_active=is_active,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [ProductResponse.model_validate(p) for p in products]


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    body: UpdateProductRequest,
    business_id: BusinessContext,
    product_service: ProductServiceDep,
    _principal: CanWriteInventory,
) -> ProductResponse:
    try:
        product = await product_service.update_product(
            business_id=business_id,
            product_id=product_id,
            **body.model_dump(exclude_unset=True),
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateSKUError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DuplicateBarcodeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidProductReferenceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ProductResponse.model_validate(product)
