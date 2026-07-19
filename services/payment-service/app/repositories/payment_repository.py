"""Repository layer for payment-service. Pure data access, no business
rules — same convention as every other service."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import PaymentTransaction, WebhookEvent


class PaymentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(
        self, *, business_id: uuid.UUID, transaction_id: uuid.UUID
    ) -> PaymentTransaction | None:
        result = await self._session.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.id == transaction_id,
                PaymentTransaction.business_id == business_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_internal_reference(
        self, *, internal_reference: str
    ) -> PaymentTransaction | None:
        """Deliberately NOT scoped by business_id — webhook handlers don't
        have an authenticated business context (the provider calls us, not
        an authenticated merchant user), so this lookup is by the globally
        unique internal_reference alone. Every other read in this service
        goes through get_by_id, which IS business_id-scoped."""
        result = await self._session.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.internal_reference == internal_reference
            )
        )
        return result.scalar_one_or_none()

    async def list_transactions(
        self,
        *,
        business_id: uuid.UUID,
        status: str | None = None,
        related_sale_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaymentTransaction]:
        stmt = select(PaymentTransaction).where(PaymentTransaction.business_id == business_id)
        if status is not None:
            stmt = stmt.where(PaymentTransaction.status == status)
        if related_sale_id is not None:
            stmt = stmt.where(PaymentTransaction.related_sale_id == related_sale_id)
        stmt = stmt.order_by(PaymentTransaction.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, transaction: PaymentTransaction) -> PaymentTransaction:
        self._session.add(transaction)
        await self._session.flush()
        return transaction

    async def update(self, transaction: PaymentTransaction) -> PaymentTransaction:
        await self._session.flush()
        return transaction

    async def get_webhook_event(
        self, *, provider: str, provider_event_key: str
    ) -> WebhookEvent | None:
        result = await self._session.execute(
            select(WebhookEvent).where(
                WebhookEvent.provider == provider,
                WebhookEvent.provider_event_key == provider_event_key,
            )
        )
        return result.scalar_one_or_none()

    async def create_webhook_event(self, event: WebhookEvent) -> WebhookEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
