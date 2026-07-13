"""
Client for sales-service -> inventory-service calls — the platform's first
real service-to-service integration.

Cross-service auth: the cashier's OWN bearer token (the one sales-service
received on the incoming request) is forwarded as-is to inventory-service,
rather than minting a separate service-account token. inventory-service
already gates /stock/batch-sale behind SALES_CREATE and /stock/batch-return
behind SALES_REFUND specifically so this works — a cashier's token
naturally has the right permissions for their own actions, and inventory-
service enforces tenant/permission checks exactly as if the cashier had
called it directly. This is the simplest correct thing for a synchronous,
user-initiated request. It stops being sufficient the moment something
needs to touch inventory-service without a live user request in flight
(a scheduled job, a webhook-triggered action) — flagged here rather than
silently assumed to generalize, since that will need real service-account
credentials and its own permission model.

Testability: SaleService depends on InventoryClientProtocol, not this
concrete class — the same Repository Pattern already used for the
database, applied to an external HTTP dependency. Tests substitute an
in-memory fake (see tests/fakes.py) so SaleService's business logic is
verified without needing a live inventory-service process.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import httpx


@dataclass(frozen=True)
class ProductSnapshot:
    """Authoritative product data fetched from inventory-service at the
    moment of sale — never trust a client-supplied price. See
    SaleService.create_sale for where this gets snapshotted onto a
    SaleItem so historical receipts stay accurate even if the product's
    current price/name later changes."""

    id: uuid.UUID
    sku: str
    name: str
    unit_price: Decimal
    is_active: bool


@dataclass(frozen=True)
class BatchStockItemDTO:
    product_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal


class InventoryClientError(Exception):
    """Base for all inventory-service call failures."""


class InventoryServiceUnavailableError(InventoryClientError):
    """Network failure, timeout, or a 5xx from inventory-service. The
    caller should treat this as 'try again later' — NOT as a business-rule
    rejection like insufficient stock, since retrying a genuine
    insufficient-stock rejection would never succeed but retrying a
    transient network blip might."""


class InsufficientStockUpstreamError(InventoryClientError):
    """inventory-service rejected the operation: not enough stock for one
    or more items (its own InsufficientStockError, surfaced as a 409)."""


class InvalidProductOrLocationError(InventoryClientError):
    """inventory-service returned 404 — a product_id/location_id in the
    request didn't exist or didn't belong to this business."""


class InventoryAuthError(InventoryClientError):
    """401/403 from inventory-service. Shouldn't normally happen if the
    original request to sales-service was itself properly authenticated,
    since the same token is just forwarded — but must be handled
    explicitly rather than surfacing as an opaque crash if it ever does
    (e.g. the token expired in the few hundred milliseconds between the
    two services, or the two services' JWT_SECRET_KEY values drift out of
    sync — see docs/PHASES.md's operational note on that)."""


class InventoryClientProtocol(Protocol):
    async def get_products_batch(
        self, *, bearer_token: str, product_ids: list[uuid.UUID]
    ) -> list[ProductSnapshot]: ...

    async def batch_sale(
        self,
        *,
        bearer_token: str,
        items: list[BatchStockItemDTO],
        reference_id: uuid.UUID,
    ) -> None: ...

    async def batch_return(
        self,
        *,
        bearer_token: str,
        items: list[BatchStockItemDTO],
        reference_id: uuid.UUID,
        reason: str,
    ) -> None: ...


class HttpInventoryClient:
    """Real implementation, used in production. Wired via DI in
    core/dependencies.py — never imported directly by SaleService."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def get_products_batch(
        self, *, bearer_token: str, product_ids: list[uuid.UUID]
    ) -> list[ProductSnapshot]:
        data = await self._post(
            "/api/v1/products/batch",
            bearer_token=bearer_token,
            json_body={"product_ids": [str(pid) for pid in product_ids]},
        )
        return [
            ProductSnapshot(
                id=uuid.UUID(item["id"]),
                sku=item["sku"],
                name=item["name"],
                unit_price=Decimal(str(item["unit_price"])),
                is_active=item["is_active"],
            )
            for item in data
        ]

    async def batch_sale(
        self,
        *,
        bearer_token: str,
        items: list[BatchStockItemDTO],
        reference_id: uuid.UUID,
    ) -> None:
        await self._post(
            "/api/v1/stock/batch-sale",
            bearer_token=bearer_token,
            json_body={
                "items": [
                    {
                        "product_id": str(i.product_id),
                        "location_id": str(i.location_id),
                        "quantity": str(i.quantity),
                    }
                    for i in items
                ],
                "reference_id": str(reference_id),
            },
        )

    async def batch_return(
        self,
        *,
        bearer_token: str,
        items: list[BatchStockItemDTO],
        reference_id: uuid.UUID,
        reason: str,
    ) -> None:
        await self._post(
            "/api/v1/stock/batch-return",
            bearer_token=bearer_token,
            json_body={
                "items": [
                    {
                        "product_id": str(i.product_id),
                        "location_id": str(i.location_id),
                        "quantity": str(i.quantity),
                    }
                    for i in items
                ],
                "reference_id": str(reference_id),
                "reason": reason,
            },
        )

    async def _post(self, path: str, *, bearer_token: str, json_body: dict) -> object:
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {bearer_token}"},
                    json=json_body,
                )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            raise InventoryServiceUnavailableError(
                f"Could not reach inventory-service at {url}: {exc}"
            ) from exc

        if response.status_code in (401, 403):
            raise InventoryAuthError(
                f"inventory-service rejected the forwarded token ({response.status_code})"
            )
        if response.status_code == 404:
            raise InvalidProductOrLocationError(response.text)
        if response.status_code == 409:
            raise InsufficientStockUpstreamError(response.text)
        if response.status_code >= 500:
            raise InventoryServiceUnavailableError(
                f"inventory-service returned {response.status_code}: {response.text}"
            )
        if response.status_code >= 400:
            # Anything else 4xx (e.g. a 422 from a malformed request WE
            # built) is a bug in sales-service's own request construction,
            # not a business-rule rejection — still surfaced as a client
            # error rather than crashing unhandled.
            raise InventoryClientError(
                f"inventory-service rejected the request ({response.status_code}): {response.text}"
            )

        return response.json()
