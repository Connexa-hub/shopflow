from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Category


class CategoryRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, *, business_id: uuid.UUID, category_id: uuid.UUID) -> Category | None:
        result = await self._session.execute(
            select(Category).where(
                Category.id == category_id, Category.business_id == business_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_business(self, *, business_id: uuid.UUID) -> list[Category]:
        result = await self._session.execute(
            select(Category).where(Category.business_id == business_id).order_by(Category.name)
        )
        return list(result.scalars().all())

    async def create(self, category: Category) -> Category:
        self._session.add(category)
        await self._session.flush()
        return category

    async def commit(self) -> None:
        await self._session.commit()
