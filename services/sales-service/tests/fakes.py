"""
In-memory fake implementing InventoryClientProtocol, used by SaleService's
test suite instead of a real HTTP call to a live inventory-service process
(which doesn't exist in a unit test run). Same Repository Pattern already
used for the database, applied to an external service dependency.

Also records every call it receives (`self.batch_sale_calls`,
`self.batch_return_calls`) so tests can assert on WHETHER a compensating
reversal happened — not just on the final state — which is the only way
to actually verify the "best-effort compensation on local failure" logic
in SaleService.create_sale.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.inventory_client import (
    BatchStockItemDTO,
    InsufficientStockUpstreamError,
    InvalidProductOrLocationError,
    InventoryServiceUnavailableError,
    ProductSnapshot,
)


@dataclass
class FakeInventoryClient:
    catalog: dict[uuid.UUID, ProductSnapshot] = field(default_factory=dict)
    stock_levels: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = field(default_factory=dict)

    # Controllable failure injection
    fail_products_lookup_with: Exception | None = None
    fail_batch_sale_with: Exception | None = None
    fail_batch_return_with: Exception | None = None

    # Call log, for asserting on behavior (e.g. "was a compensating
    # reversal actually attempted") rather than only on final state.
    batch_sale_calls: list[dict] = field(default_factory=list)
    batch_return_calls: list[dict] = field(default_factory=list)

    def add_product(
        self,
        *,
        product_id: uuid.UUID | None = None,
        sku: str = "SKU-1",
        name: str = "Test Product",
        unit_price: Decimal = Decimal("10.00"),
        is_active: bool = True,
    ) -> ProductSnapshot:
        pid = product_id or uuid.uuid4()
        snapshot = ProductSnapshot(
            id=pid, sku=sku, name=name, unit_price=unit_price, is_active=is_active
        )
        self.catalog[pid] = snapshot
        return snapshot

    async def get_products_batch(
        self, *, bearer_token: str, product_ids: list[uuid.UUID]
    ) -> list[ProductSnapshot]:
        if self.fail_products_lookup_with:
            raise self.fail_products_lookup_with
        return [self.catalog[pid] for pid in product_ids if pid in self.catalog]

    async def batch_sale(
        self,
        *,
        bearer_token: str,
        items: list[BatchStockItemDTO],
        reference_id: uuid.UUID,
    ) -> None:
        self.batch_sale_calls.append({"items": items, "reference_id": reference_id})
        if self.fail_batch_sale_with:
            raise self.fail_batch_sale_with
        for item in items:
            key = (item.product_id, item.location_id)
            current = self.stock_levels.get(key, Decimal("0"))
            if current < item.quantity:
                raise InsufficientStockUpstreamError(
                    f"Only {current} in stock for {item.product_id}"
                )
        for item in items:
            key = (item.product_id, item.location_id)
            self.stock_levels[key] = self.stock_levels.get(key, Decimal("0")) - item.quantity

    async def batch_return(
        self,
        *,
        bearer_token: str,
        items: list[BatchStockItemDTO],
        reference_id: uuid.UUID,
        reason: str,
    ) -> None:
        self.batch_return_calls.append(
            {"items": items, "reference_id": reference_id, "reason": reason}
        )
        if self.fail_batch_return_with:
            raise self.fail_batch_return_with
        for item in items:
            key = (item.product_id, item.location_id)
            self.stock_levels[key] = self.stock_levels.get(key, Decimal("0")) + item.quantity

    def set_stock(
        self, *, product_id: uuid.UUID, location_id: uuid.UUID, quantity: Decimal
    ) -> None:
        self.stock_levels[(product_id, location_id)] = quantity


__all__ = [
    "FakeInventoryClient",
    "InsufficientStockUpstreamError",
    "InvalidProductOrLocationError",
    "InventoryServiceUnavailableError",
]
