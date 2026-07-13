import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from shopflow_constants import Permission

from app.core.dependencies import SaleServiceDep
from app.core.inventory_client import (
    InsufficientStockUpstreamError,
    InvalidProductOrLocationError,
    InventoryAuthError,
    InventoryServiceUnavailableError,
)
from app.core.security import BusinessContext, CurrentPrincipal, Principal, require_permission
from app.domain.models import SaleStatus
from app.schemas.sale import (
    CreateSaleRequest,
    SaleItemResponse,
    SalePaymentResponse,
    SaleResponse,
    VoidSaleRequest,
)
from app.services.sale_service import (
    SaleAlreadyVoidedError,
    SaleItemInput,
    SaleNotFoundError,
    SalePaymentInput,
    SaleValidationError,
)

router = APIRouter(prefix="/api/v1/sales", tags=["sales"])

CanCreateSale = Annotated[Principal, Depends(require_permission(Permission.SALES_CREATE))]
CanReadSales = Annotated[Principal, Depends(require_permission(Permission.SALES_READ))]
CanRefundSale = Annotated[Principal, Depends(require_permission(Permission.SALES_REFUND))]


def _handle_inventory_errors(exc: Exception) -> HTTPException:
    """Translates the inventory_client exception hierarchy into HTTP
    responses. Centralized here so create_sale and void_sale (both of
    which call inventory-service) map errors identically rather than each
    route reinventing the same except-chain."""
    if isinstance(exc, InsufficientStockUpstreamError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, InvalidProductOrLocationError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, InventoryAuthError):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    if isinstance(exc, InventoryServiceUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))


async def _to_response(sale_service: SaleServiceDep, sale) -> SaleResponse:
    items = await sale_service.list_items(sale_id=sale.id)
    payments = await sale_service.list_payments(sale_id=sale.id)
    response = SaleResponse.model_validate(sale)
    response.items = [SaleItemResponse.model_validate(i) for i in items]
    response.payments = [SalePaymentResponse.model_validate(p) for p in payments]
    return response


@router.post("", response_model=SaleResponse, status_code=status.HTTP_201_CREATED)
async def create_sale(
    body: CreateSaleRequest,
    business_id: BusinessContext,
    sale_service: SaleServiceDep,
    principal: CurrentPrincipal,
    _permission_check: CanCreateSale,
) -> SaleResponse:
    try:
        sale = await sale_service.create_sale(
            business_id=business_id,
            location_id=body.location_id,
            cashier_id=principal.user_id,
            bearer_token=principal.raw_token,
            customer_id=body.customer_id,
            items=[
                SaleItemInput(
                    product_id=item.product_id,
                    quantity=item.quantity,
                    discount_amount=item.discount_amount,
                )
                for item in body.items
            ],
            payments=[
                SalePaymentInput(method=p.method, amount=p.amount, reference=p.reference)
                for p in body.payments
            ],
        )
    except SaleValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (
        InsufficientStockUpstreamError,
        InvalidProductOrLocationError,
        InventoryAuthError,
        InventoryServiceUnavailableError,
    ) as exc:
        raise _handle_inventory_errors(exc) from exc
    return await _to_response(sale_service, sale)


@router.get("/{sale_id}", response_model=SaleResponse)
async def get_sale(
    sale_id: uuid.UUID,
    business_id: BusinessContext,
    sale_service: SaleServiceDep,
    _principal: CanReadSales,
) -> SaleResponse:
    try:
        sale = await sale_service.get_sale(business_id=business_id, sale_id=sale_id)
    except SaleNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return await _to_response(sale_service, sale)


@router.get("", response_model=list[SaleResponse])
async def list_sales(
    business_id: BusinessContext,
    sale_service: SaleServiceDep,
    _principal: CanReadSales,
    location_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    status_filter: SaleStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[SaleResponse]:
    sales = await sale_service.list_sales(
        business_id=business_id,
        location_id=location_id,
        customer_id=customer_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return [await _to_response(sale_service, s) for s in sales]


@router.post("/{sale_id}/void", response_model=SaleResponse)
async def void_sale(
    sale_id: uuid.UUID,
    body: VoidSaleRequest,
    business_id: BusinessContext,
    sale_service: SaleServiceDep,
    principal: CurrentPrincipal,
    _permission_check: CanRefundSale,
) -> SaleResponse:
    try:
        sale = await sale_service.void_sale(
            business_id=business_id,
            sale_id=sale_id,
            bearer_token=principal.raw_token,
            reason=body.reason,
        )
    except SaleNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SaleAlreadyVoidedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SaleValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (
        InsufficientStockUpstreamError,
        InvalidProductOrLocationError,
        InventoryAuthError,
        InventoryServiceUnavailableError,
    ) as exc:
        raise _handle_inventory_errors(exc) from exc
    return await _to_response(sale_service, sale)
