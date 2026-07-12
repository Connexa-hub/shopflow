from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Location


class LocationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, *, business_id: uuid.UUID, location_id: uuid.UUID) -> Location | None:
        result = await self._session.execute(
            select(Location).where(
                Location.id == location_id, Location.business_id == business_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_business(self, *, business_id: uuid.UUID) -> list[Location]:
        result = await self._session.execute(
            select(Location).where(Location.business_id == business_id).order_by(Location.name)
        )
        return list(result.scalars().all())

    async def create(self, location: Location) -> Location:
        self._session.add(location)
        await self._session.flush()
        return location

    async def commit(self) -> None:
        await self._session.commit()
