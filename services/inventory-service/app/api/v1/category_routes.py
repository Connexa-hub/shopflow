from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from shopflow_constants import Permission

from app.core.dependencies import CategoryServiceDep
from app.core.security import BusinessContext, Principal, require_permission
from app.schemas.catalog import CategoryResponse, CreateCategoryRequest
from app.services.category_service import InvalidParentCategoryError

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])

CanReadInventory = Annotated[Principal, Depends(require_permission(Permission.INVENTORY_READ))]
CanWriteInventory = Annotated[Principal, Depends(require_permission(Permission.INVENTORY_WRITE))]


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    body: CreateCategoryRequest,
    business_id: BusinessContext,
    category_service: CategoryServiceDep,
    _principal: CanWriteInventory,
) -> CategoryResponse:
    try:
        category = await category_service.create_category(
            business_id=business_id, name=body.name, parent_id=body.parent_id
        )
    except InvalidParentCategoryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return CategoryResponse.model_validate(category)


@router.get("", response_model=list[CategoryResponse])
async def list_categories(
    business_id: BusinessContext,
    category_service: CategoryServiceDep,
    _principal: CanReadInventory,
) -> list[CategoryResponse]:
    categories = await category_service.list_categories(business_id=business_id)
    return [CategoryResponse.model_validate(c) for c in categories]
