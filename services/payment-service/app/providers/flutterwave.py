"""
Flutterwave adapter. Verified against
https://developer.flutterwave.com/docs/webhooks and the v3 Standard
Payment flow docs (fetched July 2026).

- Initialize: POST /v3/payments, amount in the MAIN currency unit as a
  string (e.g. "7500" for NGN 7,500) — unlike Paystack, Flutterwave does
  NOT use subunits here. Response: data.link (the checkout URL). No
  separate provider transaction id is returned at this step — only after
  payment, via webhook or verify.
- Verify: GET /v3/transactions/verify_by_reference?tx_ref={our_reference}
  — verifies by OUR reference directly, same shape as Paystack, so we
  never need to cache Flutterwave's own numeric transaction id just to
  check status later.
- Webhook signature — FLAGGED CAVEAT: Flutterwave's own current docs page
  (docs/webhooks) is internally inconsistent. The prose explicitly
  describes HMAC-SHA256 over the raw body, base64-encoded, compared
  against a `flutterwave-signature` header. But the runnable code examples
  further down the SAME page (Node.js/PHP/Python) just do a direct string
  comparison against that header with no HMAC computed at all. This
  implementation follows the prose (HMAC-SHA256, base64) since it's the
  more secure of the two and is the mechanism explicitly documented as the
  verification method — but this should be confirmed against a real
  Flutterwave dashboard + a live test webhook before this adapter is
  trusted in production, given the primary source disagrees with itself.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
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
    "successful": PaymentStatus.SUCCESS,
    "success": PaymentStatus.SUCCESS,
    "failed": PaymentStatus.FAILED,
    "cancelled": PaymentStatus.ABANDONED,
    "pending": PaymentStatus.PENDING,
}


class FlutterwaveAdapter:
    provider = PaymentProvider.FLUTTERWAVE

    def __init__(
        self,
        *,
        secret_key: str,
        secret_hash: str,
        base_url: str = "https://api.flutterwave.com/v3",
    ):
        self._secret_key = secret_key
        self._secret_hash = secret_hash
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
        body = await self._post(
            "/payments",
            json_body={
                "tx_ref": internal_reference,
                "amount": str(amount),
                "currency": currency,
                "redirect_url": callback_url,
                "customer": {"email": customer_email},
                "meta": metadata,
            },
        )
        data = body["data"]
        # No provider transaction id at this step — Flutterwave only
        # assigns one once payment is attempted. internal_reference is
        # the only handle we have until verify/webhook, so it doubles as
        # provider_reference for now; verify()/parse_webhook_event()
        # overwrite it with Flutterwave's real id once available.
        return InitializeResult(provider_reference=internal_reference, checkout_url=data["link"])

    async def verify(
        self, *, internal_reference: str, provider_reference: str | None
    ) -> VerifyResult:
        body = await self._get(
            "/transactions/verify_by_reference", params={"tx_ref": internal_reference}
        )
        data = body["data"]
        return VerifyResult(
            provider_reference=str(data["id"]),
            status=_STATUS_MAP.get(data["status"], PaymentStatus.PENDING),
            amount=Decimal(str(data["amount"])),
            currency=data["currency"],
            paid_at=None,  # Flutterwave's verify payload doesn't include a
            # distinct paid-at timestamp separate from created_at in the
            # shape confirmed during research; created_at is available if
            # this needs it later, but conflating "created" with "paid"
            # would be actively wrong, so this is left unset rather than
            # guessed.
        )

    def verify_webhook_signature(self, *, headers: dict[str, str], raw_body: bytes) -> bool:
        signature = headers.get("flutterwave-signature") or headers.get("Flutterwave-Signature")
        if not signature:
            return False
        expected = base64.b64encode(
            hmac.new(self._secret_hash.encode("utf-8"), raw_body, hashlib.sha256).digest()
        ).decode("utf-8")
        return hmac.compare_digest(expected, signature)

    def parse_webhook_event(self, *, raw_body: bytes) -> WebhookParseResult:
        payload = json.loads(raw_body)
        data = payload.get("data", {})
        event_key = str(payload.get("id", "")) or hashlib.sha256(raw_body).hexdigest()
        return WebhookParseResult(
            event_key=event_key,
            internal_reference=data.get("tx_ref") or data.get("reference"),
            provider_reference=str(data.get("id")) if data.get("id") else None,
            status=_STATUS_MAP.get(data.get("status", ""), PaymentStatus.PENDING),
            amount=Decimal(str(data["amount"])) if "amount" in data else None,
            currency=data.get("currency"),
        )

    async def _post(self, path: str, *, json_body: dict) -> dict:
        return await self._request("POST", path, json_body=json_body, params=None)

    async def _get(self, path: str, *, params: dict) -> dict:
        return await self._request("GET", path, json_body=None, params=params)

    async def _request(
        self, method: str, path: str, *, json_body: dict | None, params: dict | None
    ) -> dict:
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.request(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {self._secret_key}"},
                    json=json_body,
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderUnavailableError(f"Could not reach Flutterwave at {url}: {exc}") from exc

        if response.status_code == 404:
            raise TransactionNotFoundError(f"Flutterwave has no record at {path}")
        if response.status_code >= 500:
            raise ProviderUnavailableError(f"Flutterwave returned {response.status_code}")
        if response.status_code >= 400:
            raise PaymentProviderError(
                f"Flutterwave rejected the request ({response.status_code}): {response.text}"
            )
        return response.json()
