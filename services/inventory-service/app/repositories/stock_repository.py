"""
Stock data access. `apply_quantity_delta` is the one method in this whole
service that matters most for correctness under concurrency.

Why an atomic `UPDATE stock_levels SET quantity = quantity + :delta` instead
of SELECT-then-UPDATE-in-Python: a bare UPDATE with an arithmetic
expression is safe under concurrent writes on every SQL backend without
needing explicit SELECT...FOR UPDATE row locking — the UPDATE statement
itself takes the row lock for the duration of the transaction, same as it
would with an explicit lock, but with one round-trip instead of two, and
with no dialect-specific locking syntax to get wrong (SELECT...FOR UPDATE
support and semantics vary enough across backends — notably SQLite, used
in this test suite — that avoiding it entirely removes a whole class of
"works on Postgres, breaks on SQLite in CI" bugs).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Product, StockLevel, StockMovement


class StockRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_stock_level(
        self, *, product_id: uuid.UUID, location_id: uuid.UUID
    ) -> StockLevel | None:
        result = await self._session.execute(
            select(StockLevel).where(
                StockLevel.product_id == product_id, StockLevel.location_id == location_id
            )
        )
        return result.scalar_one_or_none()

    async def create_stock_level(
        self, *, business_id: uuid.UUID, product_id: uuid.UUID, location_id: uuid.UUID
    ) -> StockLevel:
        level = StockLevel(
            business_id=business_id,
            product_id=product_id,
            location_id=location_id,
            quantity=Decimal("0"),
        )
        self._session.add(level)
        await self._session.flush()
        return level

    async def apply_quantity_delta(
        self, *, product_id: uuid.UUID, location_id: uuid.UUID, delta: Decimal
    ) -> Decimal:
        """Atomically adds `delta` (may be negative) to the cached quantity
        and returns the resulting value. Caller must ensure a StockLevel
        row already exists (via create_stock_level) before calling this."""
        await self._session.execute(
            update(StockLevel)
            .where(StockLevel.product_id == product_id, StockLevel.location_id == location_id)
            .values(quantity=StockLevel.quantity + delta)
        )
        result = await self._session.execute(
            select(StockLevel.quantity).where(
                StockLevel.product_id == product_id, StockLevel.location_id == location_id
            )
        )
        return result.scalar_one()

    async def create_movement(self, movement: StockMovement) -> StockMovement:
        self._session.add(movement)
        await self._session.flush()
        return movement

    async def list_movements(
        self, *, product_id: uuid.UUID, location_id: uuid.UUID | None = None, limit: int = 50
    ) -> list[StockMovement]:
        stmt = select(StockMovement).where(StockMovement.product_id == product_id)
        if location_id is not None:
            stmt = stmt.where(StockMovement.location_id == location_id)
        stmt = stmt.order_by(StockMovement.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_low_stock(
        self, *, business_id: uuid.UUID, location_id: uuid.UUID | None = None
    ) -> list[tuple[StockLevel, Product]]:
        stmt = (
            select(StockLevel, Product)
            .join(Product, Product.id == StockLevel.product_id)
            .where(
                StockLevel.business_id == business_id,
                StockLevel.quantity <= Product.low_stock_threshold,
                Product.is_active.is_(True),
            )
        )
        if location_id is not None:
            stmt = stmt.where(StockLevel.location_id == location_id)
        result = await self._session.execute(stmt)
        # Tuple-index the Row rather than attribute-access-by-classname —
        # simpler and unambiguous for a two-entity select.
        return [(row[0], row[1]) for row in result.all()]

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
