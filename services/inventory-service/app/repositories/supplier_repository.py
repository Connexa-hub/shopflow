from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Supplier


class SupplierRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, *, business_id: uuid.UUID, supplier_id: uuid.UUID) -> Supplier | None:
        result = await self._session.execute(
            select(Supplier).where(
                Supplier.id == supplier_id, Supplier.business_id == business_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_business(self, *, business_id: uuid.UUID) -> list[Supplier]:
        result = await self._session.execute(
            select(Supplier).where(Supplier.business_id == business_id).order_by(Supplier.name)
        )
        return list(result.scalars().all())

    async def create(self, supplier: Supplier) -> Supplier:
        self._session.add(supplier)
        await self._session.flush()
        return supplier

    async def commit(self) -> None:
        await self._session.commit()
