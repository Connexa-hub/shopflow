"""
The adapter pattern the platform's payments requirement asks for
explicitly: business logic (PaymentService) depends on
PaymentProviderProtocol, never on a concrete provider class. Adding a
fourth provider later means writing one new adapter class, touching
nothing in app/services/ or app/api/.

Verified against each provider's current documentation before writing
(web searches run July 2026) rather than solely from training data, since
payment API details — endpoint paths, field names, webhook signature
schemes — are exactly the kind of thing that drifts and where getting it
wrong silently mishandles real money. Specifics and remaining uncertainty
are documented per-adapter in paystack.py/flutterwave.py/monnify.py.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.domain.models import PaymentProvider, PaymentStatus


class PaymentProviderError(Exception):
    """Base for all provider adapter failures."""


class ProviderUnavailableError(PaymentProviderError):
    """Network failure, timeout, or 5xx from the provider — treat as
    'try again later', not a business-rule rejection."""


class InvalidWebhookSignatureError(PaymentProviderError):
    """The webhook's signature didn't match — could be a forged request,
    a misconfigured secret, or (for Monnify specifically) an algorithm
    detail this codebase hasn't been able to verify with full certainty
    offline. See monnify.py for the honest caveat."""


class TransactionNotFoundError(PaymentProviderError):
    """The provider has no record of this reference."""


@dataclass(frozen=True)
class InitializeResult:
    provider_reference: str
    checkout_url: str


@dataclass(frozen=True)
class VerifyResult:
    provider_reference: str
    status: PaymentStatus
    amount: Decimal
    currency: str
    paid_at: datetime | None


@dataclass(frozen=True)
class WebhookParseResult:
    """What every adapter extracts from a raw webhook payload, in a
    provider-agnostic shape PaymentService can act on without caring
    which provider sent it."""

    event_key: str  # for idempotency dedup - see WebhookEvent model
    internal_reference: str | None
    provider_reference: str | None
    status: PaymentStatus
    amount: Decimal | None
    currency: str | None


class PaymentProviderProtocol(Protocol):
    provider: PaymentProvider

    async def initialize(
        self,
        *,
        amount: Decimal,
        currency: str,
        customer_email: str,
        internal_reference: str,
        callback_url: str,
        metadata: dict,
    ) -> InitializeResult: ...

    async def verify(
        self, *, internal_reference: str, provider_reference: str | None
    ) -> VerifyResult: ...

    def verify_webhook_signature(self, *, headers: dict[str, str], raw_body: bytes) -> bool: ...

    def parse_webhook_event(self, *, raw_body: bytes) -> WebhookParseResult: ...


def new_internal_reference(business_id: uuid.UUID) -> str:
    """Generates the reference sales-service-style code hands to whichever
    provider is chosen. Prefixed and shortened rather than a raw UUID —
    several providers (Monnify particularly) show this string back to the
    customer or in dashboard search, so a recognizable prefix helps support
    staff find a transaction quickly."""
    return f"SF-{business_id.hex[:8]}-{uuid.uuid4().hex[:12]}"
