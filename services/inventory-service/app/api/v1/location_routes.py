from typing import Annotated

from fastapi import APIRouter, Depends, status
from shopflow_constants import Permission

from app.core.dependencies import LocationServiceDep
from app.core.security import BusinessContext, Principal, require_permission
from app.schemas.catalog import CreateLocationRequest, LocationResponse

router = APIRouter(prefix="/api/v1/locations", tags=["locations"])

CanReadInventory = Annotated[Principal, Depends(require_permission(Permission.INVENTORY_READ))]
CanConfigureBusiness = Annotated[
    Principal, Depends(require_permission(Permission.BUSINESS_CONFIGURE))
]


@router.post("", response_model=LocationResponse, status_code=status.HTTP_201_CREATED)
async def create_location(
    body: CreateLocationRequest,
    business_id: BusinessContext,
    location_service: LocationServiceDep,
    _principal: CanConfigureBusiness,
) -> LocationResponse:
    # Creating a new branch is a business-configuration action (only
    # owners/managers should be able to open a new store location), not a
    # day-to-day inventory operation — hence BUSINESS_CONFIGURE rather than
    # INVENTORY_WRITE.
    location = await location_service.create_location(
        business_id=business_id, name=body.name, address=body.address, is_primary=body.is_primary
    )
    return LocationResponse.model_validate(location)


@router.get("", response_model=list[LocationResponse])
async def list_locations(
    business_id: BusinessContext,
    location_service: LocationServiceDep,
    _principal: CanReadInventory,
) -> list[LocationResponse]:
    locations = await location_service.list_locations(business_id=business_id)
    return [LocationResponse.model_validate(l) for l in locations]
