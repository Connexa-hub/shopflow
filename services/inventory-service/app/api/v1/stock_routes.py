import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from shopflow_constants import Permission

from app.core.dependencies import StockServiceDep
from app.core.security import BusinessContext, Principal, require_permission
from app.schemas.stock import (
    AdjustmentRequest,
    LowStockItemResponse,
    RestockRequest,
    SaleRequest,
    StockLevelResponse,
    StockMovementResponse,
    TransferRequest,
    WasteRequest,
)
from app.services.stock_service import InsufficientStockError, InvalidStockReferenceError

router = APIRouter(prefix="/api/v1/stock", tags=["stock"])

CanReadInventory = Annotated[Principal, Depends(require_permission(Permission.INVENTORY_READ))]
CanWriteInventory = Annotated[Principal, Depends(require_permission(Permission.INVENTORY_WRITE))]
CanCreateSale = Annotated[Principal, Depends(require_permission(Permission.SALES_CREATE))]


@router.post("/restock", response_model=StockMovementResponse, status_code=status.HTTP_201_CREATED)
async def restock(
    body: RestockRequest,
    business_id: BusinessContext,
    stock_service: StockServiceDep,
    principal: CanWriteInventory,
) -> StockMovementResponse:
    try:
        movement = await stock_service.record_restock(
            business_id=business_id,
            product_id=body.product_id,
            location_id=body.location_id,
            quantity=body.quantity,
            reference_id=body.reference_id,
            created_by=principal.user_id,
        )
    except InvalidStockReferenceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return StockMovementResponse.model_validate(movement)


@router.post("/sale", response_model=StockMovementResponse, status_code=status.HTTP_201_CREATED)
async def record_sale(
    body: SaleRequest,
    business_id: BusinessContext,
    stock_service: StockServiceDep,
    principal: CanCreateSale,
) -> StockMovementResponse:
    # Gated by SALES_CREATE (not INVENTORY_WRITE) deliberately — a cashier
    # can ring up a sale, which decrements stock as a side effect, without
    # needing broader inventory-write access. This is where sales-service
    # (Phase 3) will call in from, once it exists; exposed here directly
    # for now so the stock ledger is independently testable and usable.
    try:
        movement = await stock_service.record_sale(
            business_id=business_id,
            product_id=body.product_id,
            location_id=body.location_id,
            quantity=body.quantity,
            reference_id=body.reference_id,
            created_by=principal.user_id,
        )
    except InsufficientStockError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidStockReferenceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return StockMovementResponse.model_validate(movement)


@router.post("/adjustment", response_model=StockMovementResponse, status_code=status.HTTP_201_CREATED)
async def record_adjustment(
    body: AdjustmentRequest,
    business_id: BusinessContext,
    stock_service: StockServiceDep,
    principal: CanWriteInventory,
) -> StockMovementResponse:
    try:
        movement = await stock_service.record_adjustment(
            business_id=business_id,
            product_id=body.product_id,
            location_id=body.location_id,
            quantity_delta=body.quantity_delta,
            reason=body.reason,
            created_by=principal.user_id,
        )
    except InsufficientStockError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidStockReferenceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return StockMovementResponse.model_validate(movement)


@router.post("/waste", response_model=StockMovementResponse, status_code=status.HTTP_201_CREATED)
async def record_waste(
    body: WasteRequest,
    business_id: BusinessContext,
    stock_service: StockServiceDep,
    principal: CanWriteInventory,
) -> StockMovementResponse:
    try:
        movement = await stock_service.record_waste(
            business_id=business_id,
            product_id=body.product_id,
            location_id=body.location_id,
            quantity=body.quantity,
            reason=body.reason,
            created_by=principal.user_id,
        )
    except InsufficientStockError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidStockReferenceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return StockMovementResponse.model_validate(movement)


@router.post("/transfer", response_model=list[StockMovementResponse], status_code=status.HTTP_201_CREATED)
async def transfer_stock(
    body: TransferRequest,
    business_id: BusinessContext,
    stock_service: StockServiceDep,
    principal: CanWriteInventory,
) -> list[StockMovementResponse]:
    try:
        out_movement, in_movement = await stock_service.transfer(
            business_id=business_id,
            product_id=body.product_id,
            from_location_id=body.from_location_id,
            to_location_id=body.to_location_id,
            quantity=body.quantity,
            created_by=principal.user_id,
        )
    except InsufficientStockError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidStockReferenceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [
        StockMovementResponse.model_validate(out_movement),
        StockMovementResponse.model_validate(in_movement),
    ]


@router.get("/level", response_model=StockLevelResponse)
async def get_stock_level(
    product_id: uuid.UUID,
    location_id: uuid.UUID,
    business_id: BusinessContext,
    stock_service: StockServiceDep,
    _principal: CanReadInventory,
) -> StockLevelResponse:
    try:
        quantity = await stock_service.get_current_quantity(
            business_id=business_id, product_id=product_id, location_id=location_id
        )
    except InvalidStockReferenceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return StockLevelResponse(product_id=product_id, location_id=location_id, quantity=quantity)


@router.get("/movements", response_model=list[StockMovementResponse])
async def list_movements(
    product_id: uuid.UUID,
    business_id: BusinessContext,
    stock_service: StockServiceDep,
    _principal: CanReadInventory,
    location_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[StockMovementResponse]:
    try:
        movements = await stock_service.list_movements(
            business_id=business_id, product_id=product_id, location_id=location_id, limit=limit
        )
    except InvalidStockReferenceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [StockMovementResponse.model_validate(m) for m in movements]


@router.get("/low-stock", response_model=list[LowStockItemResponse])
async def list_low_stock(
    business_id: BusinessContext,
    stock_service: StockServiceDep,
    _principal: CanReadInventory,
    location_id: uuid.UUID | None = None,
) -> list[LowStockItemResponse]:
    items = await stock_service.list_low_stock(business_id=business_id, location_id=location_id)
    return [
        LowStockItemResponse(
            product_id=product.id,
            product_name=product.name,
            sku=product.sku,
            location_id=level.location_id,
            current_quantity=level.quantity,
            low_stock_threshold=product.low_stock_threshold,
        )
        for level, product in items
    ]
