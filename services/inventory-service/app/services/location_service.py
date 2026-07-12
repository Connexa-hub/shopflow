from __future__ import annotations

import uuid

from app.domain.models import Location
from app.repositories.location_repository import LocationRepository


class LocationNotFoundError(Exception):
    pass


class LocationService:
    def __init__(self, location_repo: LocationRepository):
        self._locations = location_repo

    async def create_location(
        self,
        *,
        business_id: uuid.UUID,
        name: str,
        address: str | None = None,
        is_primary: bool = False,
    ) -> Location:
        location = Location(
            business_id=business_id, name=name, address=address, is_primary=is_primary
        )
        created = await self._locations.create(location)
        await self._locations.commit()
        return created

    async def list_locations(self, *, business_id: uuid.UUID) -> list[Location]:
        return await self._locations.list_by_business(business_id=business_id)

    async def get_location(self, *, business_id: uuid.UUID, location_id: uuid.UUID) -> Location:
        location = await self._locations.get_by_id(
            business_id=business_id, location_id=location_id
        )
        if location is None:
            raise LocationNotFoundError(f"Location {location_id} not found")
        return location
