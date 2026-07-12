from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Product


class ProductRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, *, business_id: uuid.UUID, product_id: uuid.UUID) -> Product | None:
        result = await self._session.execute(
            select(Product).where(Product.id == product_id, Product.business_id == business_id)
        )
        return result.scalar_one_or_none()

    async def get_by_sku(self, *, business_id: uuid.UUID, sku: str) -> Product | None:
        result = await self._session.execute(
            select(Product).where(Product.business_id == business_id, Product.sku == sku)
        )
        return result.scalar_one_or_none()

    async def get_by_barcode(self, *, business_id: uuid.UUID, barcode: str) -> Product | None:
        result = await self._session.execute(
            select(Product).where(Product.business_id == business_id, Product.barcode == barcode)
        )
        return result.scalar_one_or_none()

    async def list_by_business(
        self,
        *,
        business_id: uuid.UUID,
        category_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Product]:
        stmt = select(Product).where(Product.business_id == business_id)
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        if is_active is not None:
            stmt = stmt.where(Product.is_active == is_active)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(Product.name.ilike(like), Product.sku.ilike(like)))
        stmt = stmt.order_by(Product.name).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, product: Product) -> Product:
        self._session.add(product)
        await self._session.flush()
        return product

    async def update(self, product: Product) -> Product:
        await self._session.flush()
        return product

    async def commit(self) -> None:
        await self._session.commit()
