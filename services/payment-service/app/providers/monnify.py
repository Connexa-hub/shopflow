"""
Monnify adapter. Verified against developers.monnify.com's Checkout API
and Authentication pages (fetched July 2026).

- Auth: Monnify uses OAuth2 client-credentials-style login, NOT a static
  bearer secret like Paystack/Flutterwave. POST /api/v1/auth/login with
  `Authorization: Basic base64(api_key:secret_key)` returns an access
  token valid for 1 hour. This adapter caches that token in memory and
  re-authenticates when it's within a safety margin of expiring, rather
  than logging in on every single call.
- Initialize: POST /api/v1/merchant/transactions/init-transaction with
  {amount, customerName, customerEmail, paymentReference, contractCode,
  redirectUrl, currencyCode}. Response nests everything under
  responseBody: {transactionReference, checkoutUrl, ...}. checkoutUrl
  expires in 40 minutes.
- Verify — FLAGGED CAVEAT: confirmed a "Get Transaction Status" endpoint
  exists but could not verify its exact path/parameter (our paymentReference
  vs. Monnify's own transactionReference) with full certainty during
  research. Monnify's OWN reference (transactionReference, returned at
  initialize) is used here since that's what the Pay-with-Bank-Transfer
  and similar endpoints consistently key on — but this is the least
  certain part of this adapter and should be confirmed against the live
  API reference (developers.monnify.com/api) before relying on it in
  production.
- Webhook signature: `monnify-signature` header, confirmed to exist as
  the verification mechanism. The exact HMAC algorithm (this
  implementation assumes HMAC-SHA512 over the raw body using the client
  secret key, matching the pattern Paystack uses and Monnify's own
  general security posture) was NOT explicitly confirmed character-for-
  character during research — flagged here rather than asserted with
  false confidence. Confirm against developers.monnify.com/docs/webhooks
  directly before trusting this in production.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from decimal import Decimal

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
    "PAID": PaymentStatus.SUCCESS,
    "SUCCESS": PaymentStatus.SUCCESS,
    "FAILED": PaymentStatus.FAILED,
    "OVERPAID": PaymentStatus.SUCCESS,
    "PARTIALLY_PAID": PaymentStatus.PENDING,
    "PENDING": PaymentStatus.PENDING,
    "EXPIRED": PaymentStatus.ABANDONED,
    "CANCELLED": PaymentStatus.ABANDONED,
}

# Re-authenticate this long before the token's real 1-hour expiry, so a
# slow request never straddles the boundary and gets a 401 mid-flight.
_TOKEN_REFRESH_MARGIN_SECONDS = 300


class MonnifyAdapter:
    provider = PaymentProvider.MONNIFY

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        contract_code: str,
        base_url: str = "https://api.monnify.com",
    ):
        self._api_key = api_key
        self._secret_key = secret_key
        self._contract_code = contract_code
        self._base_url = base_url.rstrip("/")
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0

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
        body = await self._post(
            "/api/v1/merchant/transactions/init-transaction",
            json_body={
                "amount": float(amount),
                "customerName": metadata.get("customer_name", customer_email),
                "customerEmail": customer_email,
                "paymentReference": internal_reference,
                "paymentDescription": metadata.get("description", "ShopFlow payment"),
                "currencyCode": currency,
                "contractCode": self._contract_code,
                "redirectUrl": callback_url,
            },
        )
        response_body = body["responseBody"]
        return InitializeResult(
            provider_reference=response_body["transactionReference"],
            checkout_url=response_body["checkoutUrl"],
        )

    async def verify(
        self, *, internal_reference: str, provider_reference: str | None
    ) -> VerifyResult:
        # See module docstring's flagged caveat — this needs Monnify's OWN
        # transactionReference (provider_reference), not our
        # paymentReference. If we've never received one yet (e.g. the
        # customer abandoned before any webhook/response gave us one),
        # there's nothing to verify against.
        if not provider_reference:
            raise TransactionNotFoundError(
                "No Monnify transactionReference on file yet for this payment"
            )
        body = await self._get(
            f"/api/v2/transactions/{provider_reference}"
        )
        response_body = body["responseBody"]
        return VerifyResult(
            provider_reference=response_body["transactionReference"],
            status=_STATUS_MAP.get(response_body["paymentStatus"], PaymentStatus.PENDING),
            amount=Decimal(str(response_body["amountPaid"])),
            currency=response_body.get("currencyCode", "NGN"),
            paid_at=None,  # not confirmed present in this exact shape during research
        )

    def verify_webhook_signature(self, *, headers: dict[str, str], raw_body: bytes) -> bool:
        signature = headers.get("monnify-signature") or headers.get("Monnify-Signature")
        if not signature:
            return False
        # See module docstring: HMAC-SHA512 assumed, not fully confirmed.
        expected = hmac.new(
            self._secret_key.encode("utf-8"), raw_body, hashlib.sha512
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_webhook_event(self, *, raw_body: bytes) -> WebhookParseResult:
        payload = json.loads(raw_body)
        event_data = payload.get("eventData", payload)
        event_key = (
            str(event_data.get("transactionReference", ""))
            or hashlib.sha256(raw_body).hexdigest()
        )
        return WebhookParseResult(
            event_key=event_key,
            internal_reference=event_data.get("paymentReference"),
            provider_reference=event_data.get("transactionReference"),
            status=_STATUS_MAP.get(event_data.get("paymentStatus", ""), PaymentStatus.PENDING),
            amount=(
                Decimal(str(event_data["amountPaid"])) if "amountPaid" in event_data else None
            ),
            currency=event_data.get("currencyCode"),
        )

    async def _get_access_token(self) -> str:
        if self._cached_token and time.monotonic() < self._token_expires_at:
            return self._cached_token

        credentials = base64.b64encode(
            f"{self._api_key}:{self._secret_key}".encode("utf-8")
        ).decode("utf-8")
        url = f"{self._base_url}/api/v1/auth/login"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, headers={"Authorization": f"Basic {credentials}"})
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderUnavailableError(f"Could not reach Monnify login at {url}: {exc}") from exc

        if response.status_code >= 400:
            raise PaymentProviderError(
                f"Monnify login rejected ({response.status_code}): {response.text}"
            )

        body = response.json()
        response_body = body["responseBody"]
        token = response_body["accessToken"]
        expires_in = response_body.get("expiresIn", 3600)

        self._cached_token = token
        self._token_expires_at = time.monotonic() + expires_in - _TOKEN_REFRESH_MARGIN_SECONDS
        return token

    async def _post(self, path: str, *, json_body: dict) -> dict:
        return await self._request("POST", path, json_body=json_body)

    async def _get(self, path: str) -> dict:
        return await self._request("GET", path, json_body=None)

    async def _request(self, method: str, path: str, *, json_body: dict | None) -> dict:
        token = await self._get_access_token()
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.request(
                    method, url, headers={"Authorization": f"Bearer {token}"}, json=json_body
                )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderUnavailableError(f"Could not reach Monnify at {url}: {exc}") from exc

        if response.status_code == 404:
            raise TransactionNotFoundError(f"Monnify has no record at {path}")
        if response.status_code >= 500:
            raise ProviderUnavailableError(f"Monnify returned {response.status_code}")
        if response.status_code >= 400:
            raise PaymentProviderError(
                f"Monnify rejected the request ({response.status_code}): {response.text}"
            )
        return response.json()
