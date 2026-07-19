import json
import uuid
from decimal import Decimal

import pytest

from app.domain.models import PaymentProvider, PaymentPurpose, PaymentStatus
from app.providers.base import WebhookParseResult
from app.repositories.payment_repository import PaymentRepository
from app.services.payment_service import (
    InvalidWebhookError,
    PaymentNotFoundError,
    PaymentService,
    PaymentValidationError,
)


@pytest.fixture
def payment_service(db_session, fake_paystack):
    return PaymentService(
        PaymentRepository(db_session),
        {PaymentProvider.PAYSTACK: fake_paystack},
        callback_base_url="http://localhost:8004",
    )


class TestInitializePayment:
    async def test_initializes_successfully(self, payment_service, business_id):
        transaction = await payment_service.initialize_payment(
            business_id=business_id,
            provider=PaymentProvider.PAYSTACK,
            amount=Decimal("2500.00"),
            currency="NGN",
            customer_email="buyer@example.com",
            purpose=PaymentPurpose.SALE_PAYMENT,
        )
        assert transaction.status == PaymentStatus.PENDING.value
        assert transaction.amount == Decimal("2500.00")
        assert transaction.checkout_url is not None
        assert transaction.internal_reference.startswith("SF-")

    async def test_rejects_non_positive_amount(self, payment_service, business_id):
        with pytest.raises(PaymentValidationError):
            await payment_service.initialize_payment(
                business_id=business_id,
                provider=PaymentProvider.PAYSTACK,
                amount=Decimal("0"),
                currency="NGN",
                customer_email="buyer@example.com",
                purpose=PaymentPurpose.SALE_PAYMENT,
            )

    async def test_rejects_unconfigured_provider(self, payment_service, business_id):
        with pytest.raises(PaymentValidationError):
            await payment_service.initialize_payment(
                business_id=business_id,
                provider=PaymentProvider.MONNIFY,  # not in this fixture's registry
                amount=Decimal("100"),
                currency="NGN",
                customer_email="buyer@example.com",
                purpose=PaymentPurpose.SALE_PAYMENT,
            )

    async def test_callback_url_built_from_internal_reference(
        self, payment_service, fake_paystack, business_id
    ):
        transaction = await payment_service.initialize_payment(
            business_id=business_id,
            provider=PaymentProvider.PAYSTACK,
            amount=Decimal("100"),
            currency="NGN",
            customer_email="buyer@example.com",
            purpose=PaymentPurpose.SALE_PAYMENT,
        )
        call = fake_paystack.initialize_calls[0]
        assert transaction.internal_reference in call["callback_url"]


class TestGetAndListPayments:
    async def test_get_payment_by_id(self, payment_service, business_id):
        created = await payment_service.initialize_payment(
            business_id=business_id,
            provider=PaymentProvider.PAYSTACK,
            amount=Decimal("100"),
            currency="NGN",
            customer_email="buyer@example.com",
            purpose=PaymentPurpose.SALE_PAYMENT,
        )
        fetched = await payment_service.get_payment(
            business_id=business_id, transaction_id=created.id
        )
        assert fetched.id == created.id

    async def test_get_nonexistent_payment_raises(self, payment_service, business_id):
        with pytest.raises(PaymentNotFoundError):
            await payment_service.get_payment(business_id=business_id, transaction_id=uuid.uuid4())

    async def test_cannot_get_another_businesss_payment(self, payment_service, business_id):
        created = await payment_service.initialize_payment(
            business_id=business_id,
            provider=PaymentProvider.PAYSTACK,
            amount=Decimal("100"),
            currency="NGN",
            customer_email="buyer@example.com",
            purpose=PaymentPurpose.SALE_PAYMENT,
        )
        with pytest.raises(PaymentNotFoundError):
            await payment_service.get_payment(business_id=uuid.uuid4(), transaction_id=created.id)

    async def test_list_payments_returns_created(self, payment_service, business_id):
        await payment_service.initialize_payment(
            business_id=business_id,
            provider=PaymentProvider.PAYSTACK,
            amount=Decimal("100"),
            currency="NGN",
            customer_email="buyer@example.com",
            purpose=PaymentPurpose.SALE_PAYMENT,
        )
        results = await payment_service.list_payments(business_id=business_id)
        assert len(results) == 1


class TestVerifyPayment:
    async def test_verify_updates_status_to_success(
        self, payment_service, fake_paystack, business_id
    ):
        transaction = await payment_service.initialize_payment(
            business_id=business_id,
            provider=PaymentProvider.PAYSTACK,
            amount=Decimal("100"),
            currency="NGN",
            customer_email="buyer@example.com",
            purpose=PaymentPurpose.SALE_PAYMENT,
        )
        fake_paystack.mark_paid(internal_reference=transaction.internal_reference)

        verified = await payment_service.verify_payment(
            business_id=business_id, transaction_id=transaction.id
        )
        assert verified.status == PaymentStatus.SUCCESS.value
        assert verified.verified_at is not None

    async def test_verify_before_payment_stays_pending(self, payment_service, business_id):
        transaction = await payment_service.initialize_payment(
            business_id=business_id,
            provider=PaymentProvider.PAYSTACK,
            amount=Decimal("100"),
            currency="NGN",
            customer_email="buyer@example.com",
            purpose=PaymentPurpose.SALE_PAYMENT,
        )
        verified = await payment_service.verify_payment(
            business_id=business_id, transaction_id=transaction.id
        )
        assert verified.status == PaymentStatus.PENDING.value

    async def test_success_status_never_reverts(self, payment_service, fake_paystack, business_id):
        """Once a transaction is marked SUCCESS, a later verify/webhook
        reporting a different status must never un-succeed it — a
        provider retry or an out-of-order webhook shouldn't be able to
        flip a completed payment back to pending/failed."""
        transaction = await payment_service.initialize_payment(
            business_id=business_id,
            provider=PaymentProvider.PAYSTACK,
            amount=Decimal("100"),
            currency="NGN",
            customer_email="buyer@example.com",
            purpose=PaymentPurpose.SALE_PAYMENT,
        )
        fake_paystack.mark_paid(internal_reference=transaction.internal_reference)
        await payment_service.verify_payment(business_id=business_id, transaction_id=transaction.id)

        # Simulate the provider now (incorrectly, or out of order) reporting pending again.
        fake_paystack._transactions[transaction.internal_reference]["status"] = PaymentStatus.PENDING
        re_verified = await payment_service.verify_payment(
            business_id=business_id, transaction_id=transaction.id
        )
        assert re_verified.status == PaymentStatus.SUCCESS.value


class TestWebhookHandling:
    def _make_webhook_body(self, **overrides) -> bytes:
        payload = {"event": "charge.success", "data": {"reference": "test-ref", "amount": 10000}}
        payload.update(overrides)
        return json.dumps(payload).encode("utf-8")

    async def test_valid_webhook_updates_transaction(
        self, payment_service, fake_paystack, business_id
    ):
        transaction = await payment_service.initialize_payment(
            business_id=business_id,
            provider=PaymentProvider.PAYSTACK,
            amount=Decimal("100"),
            currency="NGN",
            customer_email="buyer@example.com",
            purpose=PaymentPurpose.SALE_PAYMENT,
        )
        raw_body = self._make_webhook_body()
        fake_paystack.next_webhook_parse_result = WebhookParseResult(
            event_key="evt-1",
            internal_reference=transaction.internal_reference,
            provider_reference=transaction.provider_reference,
            status=PaymentStatus.SUCCESS,
            amount=Decimal("100"),
            currency="NGN",
        )

        await payment_service.handle_webhook(
            provider=PaymentProvider.PAYSTACK, headers={}, raw_body=raw_body
        )

        updated = await payment_service.get_payment(
            business_id=business_id, transaction_id=transaction.id
        )
        assert updated.status == PaymentStatus.SUCCESS.value

    async def test_invalid_signature_raises(self, payment_service, fake_paystack):
        fake_paystack.next_webhook_signature_valid = False
        with pytest.raises(InvalidWebhookError):
            await payment_service.handle_webhook(
                provider=PaymentProvider.PAYSTACK, headers={}, raw_body=b"{}"
            )

    async def test_duplicate_webhook_is_not_reprocessed(
        self, payment_service, fake_paystack, business_id
    ):
        transaction = await payment_service.initialize_payment(
            business_id=business_id,
            provider=PaymentProvider.PAYSTACK,
            amount=Decimal("100"),
            currency="NGN",
            customer_email="buyer@example.com",
            purpose=PaymentPurpose.SALE_PAYMENT,
        )
        raw_body = self._make_webhook_body()
        fake_paystack.next_webhook_parse_result = WebhookParseResult(
            event_key="evt-duplicate-test",
            internal_reference=transaction.internal_reference,
            provider_reference=transaction.provider_reference,
            status=PaymentStatus.SUCCESS,
            amount=Decimal("100"),
            currency="NGN",
        )

        await payment_service.handle_webhook(
            provider=PaymentProvider.PAYSTACK, headers={}, raw_body=raw_body
        )
        # Deliver the exact same event again — must not raise, and must
        # not somehow un-succeed or re-verify a second time.
        await payment_service.handle_webhook(
            provider=PaymentProvider.PAYSTACK, headers={}, raw_body=raw_body
        )

        updated = await payment_service.get_payment(
            business_id=business_id, transaction_id=transaction.id
        )
        assert updated.status == PaymentStatus.SUCCESS.value

    async def test_webhook_with_unknown_reference_does_not_raise(self, payment_service, fake_paystack):
        """A webhook for a reference we have no local record of shouldn't
        crash — it should be logged and acknowledged, not raise."""
        raw_body = self._make_webhook_body()
        fake_paystack.next_webhook_parse_result = WebhookParseResult(
            event_key="evt-unknown-ref",
            internal_reference="SF-doesnotexist-000000000000",
            provider_reference=None,
            status=PaymentStatus.SUCCESS,
            amount=Decimal("100"),
            currency="NGN",
        )
        await payment_service.handle_webhook(
            provider=PaymentProvider.PAYSTACK, headers={}, raw_body=raw_body
        )  # should not raise
