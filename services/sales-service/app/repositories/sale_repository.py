"""
Repository layer for sales-service. Pure data access, no business rules —
see auth-service/inventory-service for the same convention.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import ReceiptCounter, Sale, SaleItem, SalePayment


class SaleRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, *, business_id: uuid.UUID, sale_id: uuid.UUID) -> Sale | None:
        result = await self._session.execute(
            select(Sale).where(Sale.id == sale_id, Sale.business_id == business_id)
        )
        return result.scalar_one_or_none()

    async def list_sales(
        self,
        *,
        business_id: uuid.UUID,
        location_id: uuid.UUID | None = None,
        customer_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Sale]:
        stmt = select(Sale).where(Sale.business_id == business_id)
        if location_id is not None:
            stmt = stmt.where(Sale.location_id == location_id)
        if customer_id is not None:
            stmt = stmt.where(Sale.customer_id == customer_id)
        if status is not None:
            stmt = stmt.where(Sale.status == status)
        stmt = stmt.order_by(Sale.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_items(self, *, sale_id: uuid.UUID) -> list[SaleItem]:
        result = await self._session.execute(
            select(SaleItem).where(SaleItem.sale_id == sale_id)
        )
        return list(result.scalars().all())

    async def list_payments(self, *, sale_id: uuid.UUID) -> list[SalePayment]:
        result = await self._session.execute(
            select(SalePayment).where(SalePayment.sale_id == sale_id)
        )
        return list(result.scalars().all())

    async def create_sale_with_items_and_payments(
        self, *, sale: Sale, items: list[SaleItem], payments: list[SalePayment]
    ) -> Sale:
        self._session.add(sale)
        for item in items:
            item.sale_id = sale.id
            self._session.add(item)
        for payment in payments:
            payment.sale_id = sale.id
            self._session.add(payment)
        await self._session.flush()
        return sale

    async def update(self, sale: Sale) -> Sale:
        await self._session.flush()
        return sale

    async def get_next_receipt_number(self, *, business_id: uuid.UUID) -> int:
        """Atomically increments and returns a per-business receipt
        sequence. Same pattern as StockRepository.apply_quantity_delta —
        a single UPDATE ... SET last_number = last_number + 1 takes a row
        lock for the duration of the transaction on every mainstream SQL
        backend (safe under concurrency), then a plain SELECT reads the
        result back, avoiding any dependency on RETURNING-clause support
        (inconsistent across SQLite versions) or explicit FOR UPDATE
        syntax (inconsistent across dialects entirely)."""
        existing = await self._session.get(ReceiptCounter, business_id)
        if existing is None:
            counter = ReceiptCounter(business_id=business_id, last_number=0)
            self._session.add(counter)
            await self._session.flush()

        await self._session.execute(
            update(ReceiptCounter)
            .where(ReceiptCounter.business_id == business_id)
            .values(last_number=ReceiptCounter.last_number + 1)
        )
        result = await self._session.execute(
            select(ReceiptCounter.last_number).where(ReceiptCounter.business_id == business_id)
        )
        return result.scalar_one()

    async def commit(self) -> None:
        await self._session.commit()
