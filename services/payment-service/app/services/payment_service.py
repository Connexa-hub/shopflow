"""
Business logic for the payment provider adapters.

Idempotent webhook handling: every provider (Paystack, Flutterwave, and by
inference Monnify) explicitly retries webhook delivery on anything other
than a 200 response, and Flutterwave's own docs warn that even a single
legitimate event can arrive more than once. handle_webhook records every
event by (provider, provider_event_key) before doing anything else — a
retried or duplicate delivery is recognized and acknowledged with 200
without reprocessing, rather than risking a double status flip.

Rollback-on-failure: every method that writes then commits explicitly
rolls back on an unhandled exception rather than assuming the caller's
session will be discarded correctly — this was a real bug found and fixed
in inventory-service/sales-service earlier (see docs/PHASES.md), applied
here from the start rather than waiting to rediscover it a third time.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.domain.models import (
    PaymentProvider,
    PaymentPurpose,
    PaymentStatus,
    PaymentTransaction,
    WebhookEvent,
)
from app.providers.base import (
    PaymentProviderProtocol,
    TransactionNotFoundError,
    new_internal_reference,
)
from app.repositories.payment_repository import PaymentRepository


class PaymentValidationError(Exception):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PaymentNotFoundError(Exception):
    pass


class InvalidWebhookError(Exception):
    """Signature verification failed, or the payload couldn't be parsed —
    the caller (API route) should respond 401/400, never 200, so the
    provider knows to treat this delivery as rejected."""


class PaymentService:
    def __init__(
        self,
        payment_repo: PaymentRepository,
        providers: dict[PaymentProvider, PaymentProviderProtocol],
        *,
        callback_base_url: str,
    ):
        self._payments = payment_repo
        self._providers = providers
        self._callback_base_url = callback_base_url.rstrip("/")

    def _get_provider(self, provider: PaymentProvider) -> PaymentProviderProtocol:
        adapter = self._providers.get(provider)
        if adapter is None:
            raise PaymentValidationError(f"Provider '{provider.value}' is not configured")
        return adapter

    async def initialize_payment(
        self,
        *,
        business_id: uuid.UUID,
        provider: PaymentProvider,
        amount: Decimal,
        currency: str,
        customer_email: str,
        purpose: PaymentPurpose,
        related_sale_id: uuid.UUID | None = None,
        customer_id: uuid.UUID | None = None,
        metadata: dict | None = None,
    ) -> PaymentTransaction:
        if amount <= 0:
            raise PaymentValidationError("Payment amount must be positive")

        adapter = self._get_provider(provider)
        internal_reference = new_internal_reference(business_id)
        callback_url = f"{self._callback_base_url}/api/v1/payments/{internal_reference}/callback"

        result = await adapter.initialize(
            amount=amount,
            currency=currency,
            customer_email=customer_email,
            internal_reference=internal_reference,
            callback_url=callback_url,
            metadata=metadata or {},
        )

        transaction = PaymentTransaction(
            business_id=business_id,
            provider=provider.value,
            status=PaymentStatus.PENDING.value,
            purpose=purpose.value,
            internal_reference=internal_reference,
            provider_reference=result.provider_reference,
            amount=amount,
            currency=currency,
            customer_email=customer_email,
            customer_id=customer_id,
            related_sale_id=related_sale_id,
            checkout_url=result.checkout_url,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        try:
            await self._payments.create(transaction)
            await self._payments.commit()
        except Exception:
            # The provider-side transaction now exists with no local
            # record of it — same class of cross-system gap documented in
            # sales-service's create_sale, and the same honest limitation:
            # there is no local write left to roll back further damage
            # from (nothing else was written), but this IS a case a
            # reconciliation job would need to catch later by listing the
            # provider's recent transactions and finding one with no
            # matching local row.
            await self._payments.rollback()
            raise
        return transaction

    async def get_payment(
        self, *, business_id: uuid.UUID, transaction_id: uuid.UUID
    ) -> PaymentTransaction:
        transaction = await self._payments.get_by_id(
            business_id=business_id, transaction_id=transaction_id
        )
        if transaction is None:
            raise PaymentNotFoundError(f"Payment {transaction_id} not found")
        return transaction

    async def list_payments(
        self,
        *,
        business_id: uuid.UUID,
        status: PaymentStatus | None = None,
        related_sale_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaymentTransaction]:
        return await self._payments.list_transactions(
            business_id=business_id,
            status=status.value if status else None,
            related_sale_id=related_sale_id,
            limit=limit,
            offset=offset,
        )

    async def verify_payment(
        self, *, business_id: uuid.UUID, transaction_id: uuid.UUID
    ) -> PaymentTransaction:
        """Active polling path — the customer-facing callback/redirect
        page calls this to confirm status rather than trusting redirect
        query params alone (every provider's docs explicitly warn against
        that: redirect parameters can be manipulated client-side)."""
        transaction = await self.get_payment(
            business_id=business_id, transaction_id=transaction_id
        )
        adapter = self._get_provider(PaymentProvider(transaction.provider))

        try:
            result = await adapter.verify(
                internal_reference=transaction.internal_reference,
                provider_reference=transaction.provider_reference,
            )
        except TransactionNotFoundError:
            return transaction  # nothing to update yet; still pending

        await self._apply_result(
            transaction,
            status=result.status,
            provider_reference=result.provider_reference,
            paid_at=result.paid_at,
        )
        return transaction

    async def handle_webhook(
        self, *, provider: PaymentProvider, headers: dict[str, str], raw_body: bytes
    ) -> None:
        adapter = self._get_provider(provider)

        if not adapter.verify_webhook_signature(headers=headers, raw_body=raw_body):
            raise InvalidWebhookError(f"Signature verification failed for {provider.value}")

        try:
            parsed = adapter.parse_webhook_event(raw_body=raw_body)
        except (ValueError, KeyError) as exc:
            raise InvalidWebhookError(
                f"Could not parse {provider.value} webhook payload"
            ) from exc

        existing_event = await self._payments.get_webhook_event(
            provider=provider.value, provider_event_key=parsed.event_key
        )
        if existing_event is not None and existing_event.processed_at is not None:
            return  # already processed — acknowledge without reprocessing

        # Everything from here is one logical operation (event bookkeeping
        # + transaction status update) committed together — if anything
        # raises partway through, roll back explicitly rather than assume
        # the caller's session gets discarded (the same lesson learned the
        # hard way in inventory-service; see docs/PHASES.md).
        try:
            if existing_event is None:
                event = WebhookEvent(
                    provider=provider.value,
                    provider_event_key=parsed.event_key,
                    internal_reference=parsed.internal_reference,
                    raw_payload=raw_body.decode("utf-8", errors="replace"),
                )
                await self._payments.create_webhook_event(event)
            else:
                event = existing_event

            transaction = None
            if parsed.internal_reference is not None:
                transaction = await self._payments.get_by_internal_reference(
                    internal_reference=parsed.internal_reference
                )
                if transaction is not None:
                    await self._apply_result_no_commit(
                        transaction,
                        status=parsed.status,
                        provider_reference=(
                            parsed.provider_reference or transaction.provider_reference
                        ),
                        paid_at=None,
                    )
            # If parsed.internal_reference is None, there's no local
            # transaction to locate — the event is still logged above (for
            # audit/debugging) but there's nothing further to apply. This
            # shouldn't normally happen if an adapter's parse logic is
            # correct, since we always send our own reference to the
            # provider at initialize time.

            event.processed_at = _utc_now()
            await self._payments.update(event)
            await self._payments.commit()
        except Exception:
            await self._payments.rollback()
            raise


    async def _apply_result_no_commit(
        self,
        transaction: PaymentTransaction,
        *,
        status: PaymentStatus,
        provider_reference: str | None,
        paid_at: datetime | None,
    ) -> None:
        """Does the status-update logic but does NOT commit — see
        inventory-service's _apply_movement/record_batch_sale for why a
        caller doing several writes as one logical operation (here:
        updating the transaction AND the webhook event together) should
        commit once at the end, not once per write."""
        if transaction.status == PaymentStatus.SUCCESS.value:
            return  # already finalized — never let a later event un-succeed it

        transaction.status = status.value
        if provider_reference:
            transaction.provider_reference = provider_reference
        if status == PaymentStatus.SUCCESS:
            transaction.verified_at = paid_at or transaction.verified_at

        await self._payments.update(transaction)

    async def _apply_result(
        self,
        transaction: PaymentTransaction,
        *,
        status: PaymentStatus,
        provider_reference: str | None,
        paid_at: datetime | None,
    ) -> None:
        """Single-write entry point that commits immediately — used by
        verify_payment, whose only write is this one. handle_webhook uses
        _apply_result_no_commit directly instead, since it has a second
        write (the webhook event bookkeeping) to commit together with
        this one."""
        try:
            await self._apply_result_no_commit(
                transaction, status=status, provider_reference=provider_reference, paid_at=paid_at
            )
            await self._payments.commit()
        except Exception:
            await self._payments.rollback()
            raise
