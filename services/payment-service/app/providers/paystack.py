"""
Paystack adapter. Verified against https://paystack.com/docs/payments/
accept-payments/ and https://paystack.com/docs/payments/webhooks/
(fetched July 2026).

- Initialize: POST /transaction/initialize, amount in the SMALLEST
  currency unit (kobo for NGN, pesewas for GHS, cents for ZAR) — Paystack
  does not accept decimal amounts, so we multiply by 100 and round to an
  integer. Response: data.authorization_url, data.reference,
  data.access_code.
- Verify: GET /transaction/verify/{reference} using OUR reference string
  (Paystack echoes back whatever reference we supplied at initialize).
- Webhook signature: X-Paystack-Signature header = HMAC-SHA512 of the RAW
  request body bytes (not a re-serialized/re-encoded version — several
  real-world implementations get this wrong by hashing
  json.dumps(parsed_body) instead of the original bytes, which produces a
  different signature whenever key order or whitespace differs from the
  original transmission).
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import httpx

from app.domain.models import PaymentProvider, PaymentStatus
from app.providers.base import (
    InitializeResult,
    PaymentProviderError,
    ProviderUnavailableError,
    TransactionNotFoundError,
    VerifyResult,
    WebhookParseResult,
)

_STATUS_MAP = {
    "success": PaymentStatus.SUCCESS,
    "failed": PaymentStatus.FAILED,
    "abandoned": PaymentStatus.ABANDONED,
    "pending": PaymentStatus.PENDING,
    "reversed": PaymentStatus.FAILED,
}


class PaystackAdapter:
    provider = PaymentProvider.PAYSTACK

    def __init__(self, *, secret_key: str, base_url: str = "https://api.paystack.co"):
        self._secret_key = secret_key
        self._base_url = base_url.rstrip("/")

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
        amount_subunits = int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
        body = await self._post(
            "/transaction/initialize",
            json_body={
                "email": customer_email,
                "amount": str(amount_subunits),
                "currency": currency,
                "reference": internal_reference,
                "callback_url": callback_url,
                "metadata": metadata,
            },
        )
        data = body["data"]
        return InitializeResult(
            provider_reference=data["reference"], checkout_url=data["authorization_url"]
        )

    async def verify(
        self, *, internal_reference: str, provider_reference: str | None
    ) -> VerifyResult:
        # Paystack verifies by the reference WE supplied at initialize
        # time, which is internal_reference — provider_reference isn't
        # needed here, but kept in the signature for Protocol consistency
        # with adapters that DO need their own reference to verify.
        try:
            body = await self._get(f"/transaction/verify/{internal_reference}")
        except TransactionNotFoundError:
            raise

        data = body["data"]
        paid_at = None
        if data.get("paid_at"):
            paid_at = datetime.fromisoformat(data["paid_at"].replace("Z", "+00:00"))

        return VerifyResult(
            provider_reference=data["reference"],
            status=_STATUS_MAP.get(data["status"], PaymentStatus.PENDING),
            amount=Decimal(str(data["amount"])) / 100,
            currency=data["currency"],
            paid_at=paid_at,
        )

    def verify_webhook_signature(self, *, headers: dict[str, str], raw_body: bytes) -> bool:
        signature = headers.get("x-paystack-signature") or headers.get("X-Paystack-Signature")
        if not signature:
            return False
        expected = hmac.new(
            self._secret_key.encode("utf-8"), raw_body, hashlib.sha512
        ).hexdigest()
        # Constant-time comparison — a naive `==` on signature strings is
        # a timing side-channel, small but unnecessary to accept here.
        return hmac.compare_digest(expected, signature)

    def parse_webhook_event(self, *, raw_body: bytes) -> WebhookParseResult:
        payload = json.loads(raw_body)
        data = payload.get("data", {})
        event_id = str(data.get("id", "")) or hashlib.sha256(raw_body).hexdigest()
        return WebhookParseResult(
            event_key=event_id,
            internal_reference=data.get("reference"),
            provider_reference=data.get("reference"),
            status=_STATUS_MAP.get(data.get("status", ""), PaymentStatus.PENDING),
            amount=Decimal(str(data["amount"])) / 100 if "amount" in data else None,
            currency=data.get("currency"),
        )

    async def _post(self, path: str, *, json_body: dict) -> dict:
        return await self._request("POST", path, json_body=json_body)

    async def _get(self, path: str) -> dict:
        return await self._request("GET", path, json_body=None)

    async def _request(self, method: str, path: str, *, json_body: dict | None) -> dict:
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.request(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {self._secret_key}"},
                    json=json_body,
                )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderUnavailableError(f"Could not reach Paystack at {url}: {exc}") from exc

        if response.status_code == 404:
            raise TransactionNotFoundError(f"Paystack has no record at {path}")
        if response.status_code >= 500:
            raise ProviderUnavailableError(f"Paystack returned {response.status_code}")
        if response.status_code >= 400:
            raise PaymentProviderError(
                f"Paystack rejected the request ({response.status_code}): {response.text}"
            )
        return response.json()
