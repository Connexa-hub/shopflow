"""
In-memory fake implementing PaymentProviderProtocol, used instead of a
real HTTP call to Paystack/Flutterwave/Monnify — same Repository Pattern
already used for the database and for inventory-service's
InventoryClientProtocol in sales-service, applied here to the third-party
provider dependency.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from app.domain.models import PaymentProvider, PaymentStatus
from app.providers.base import (
    InitializeResult,
    ProviderUnavailableError,
    VerifyResult,
    WebhookParseResult,
)


@dataclass
class FakeProviderAdapter:
    provider: PaymentProvider = PaymentProvider.PAYSTACK
    fixed_checkout_url: str = "https://checkout.example.test/pay/abc123"

    fail_initialize_with: Exception | None = None
    fail_verify_with: Exception | None = None

    # Controllable webhook behavior for tests
    next_webhook_signature_valid: bool = True
    next_webhook_parse_result: WebhookParseResult | None = None

    # Call log for assertions
    initialize_calls: list[dict] = field(default_factory=list)
    verify_calls: list[dict] = field(default_factory=list)

    # Simulated provider-side transaction state, keyed by internal_reference
    _transactions: dict[str, dict] = field(default_factory=dict)

    async def initialize(
        self,
        *,
        amount: Decimal,
        currency: str,
        customer_email: str,
        internal_reference: str,
        callback_url: str,
        metadata: dict,
    ) -> InitializeResult:
        self.initialize_calls.append(
            {
                "amount": amount,
                "currency": currency,
                "customer_email": customer_email,
                "internal_reference": internal_reference,
                "callback_url": callback_url,
                "metadata": metadata,
            }
        )
        if self.fail_initialize_with:
            raise self.fail_initialize_with

        provider_reference = f"fake-{uuid.uuid4().hex[:10]}"
        self._transactions[internal_reference] = {
            "provider_reference": provider_reference,
            "status": PaymentStatus.PENDING,
            "amount": amount,
            "currency": currency,
        }
        return InitializeResult(
            provider_reference=provider_reference, checkout_url=self.fixed_checkout_url
        )

    async def verify(
        self, *, internal_reference: str, provider_reference: str | None
    ) -> VerifyResult:
        self.verify_calls.append(
            {"internal_reference": internal_reference, "provider_reference": provider_reference}
        )
        if self.fail_verify_with:
            raise self.fail_verify_with

        record = self._transactions.get(internal_reference, {})
        return VerifyResult(
            provider_reference=record.get("provider_reference", provider_reference or ""),
            status=record.get("status", PaymentStatus.PENDING),
            amount=record.get("amount", Decimal("0")),
            currency=record.get("currency", "NGN"),
            paid_at=datetime.now(timezone.utc) if record.get("status") == PaymentStatus.SUCCESS else None,
        )

    def mark_paid(self, *, internal_reference: str) -> None:
        """Test helper — simulates the provider confirming payment, used
        before calling verify() to exercise the success path."""
        if internal_reference in self._transactions:
            self._transactions[internal_reference]["status"] = PaymentStatus.SUCCESS

    def verify_webhook_signature(self, *, headers: dict[str, str], raw_body: bytes) -> bool:
        return self.next_webhook_signature_valid

    def parse_webhook_event(self, *, raw_body: bytes) -> WebhookParseResult:
        if self.next_webhook_parse_result is not None:
            return self.next_webhook_parse_result
        # Default: derive a deterministic event key from the body so
        # identical payloads dedupe naturally in tests that don't set an
        # explicit parse result.
        return WebhookParseResult(
            event_key=hashlib.sha256(raw_body).hexdigest(),
            internal_reference=None,
            provider_reference=None,
            status=PaymentStatus.SUCCESS,
            amount=None,
            currency=None,
        )


__all__ = ["FakeProviderAdapter", "ProviderUnavailableError"]
