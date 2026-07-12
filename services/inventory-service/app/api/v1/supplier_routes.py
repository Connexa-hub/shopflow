from typing import Annotated

from fastapi import APIRouter, Depends, status
from shopflow_constants import Permission

from app.core.dependencies import SupplierServiceDep
from app.core.security import BusinessContext, Principal, require_permission
from app.schemas.catalog import CreateSupplierRequest, SupplierResponse

router = APIRouter(prefix="/api/v1/suppliers", tags=["suppliers"])

CanReadInventory = Annotated[Principal, Depends(require_permission(Permission.INVENTORY_READ))]
CanWriteInventory = Annotated[Principal, Depends(require_permission(Permission.INVENTORY_WRITE))]


@router.post("", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    body: CreateSupplierRequest,
    business_id: BusinessContext,
    supplier_service: SupplierServiceDep,
    _principal: CanWriteInventory,
) -> SupplierResponse:
    supplier = await supplier_service.create_supplier(
        business_id=business_id,
        name=body.name,
        phone_number=body.phone_number,
        email=body.email,
        address=body.address,
    )
    return SupplierResponse.model_validate(supplier)


@router.get("", response_model=list[SupplierResponse])
async def list_suppliers(
    business_id: BusinessContext,
    supplier_service: SupplierServiceDep,
    _principal: CanReadInventory,
) -> list[SupplierResponse]:
    suppliers = await supplier_service.list_suppliers(business_id=business_id)
    return [SupplierResponse.model_validate(s) for s in suppliers]
