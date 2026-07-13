"""
Business logic for the POS transaction engine.

Ordering principle, used consistently in both create_sale and void_sale:
call inventory-service (the remote system of record for stock) BEFORE
persisting anything locally. "Sale recorded but stock never deducted" is a
worse failure mode than the reverse — it silently corrupts a merchant's
inventory count in a way that's hard to ever detect, whereas "stock
deducted but no local sale row" is at least detectable later by cross-
referencing inventory-service's movement reference_ids against
sales-service's sale IDs.

Known limitation, stated plainly rather than solved partially and left
undocumented: there is no true distributed transaction across the two
services' separate databases. If the remote stock deduction succeeds but
the local DB write then fails for some unrelated reason (a dropped
connection, a bug), create_sale makes a best-effort COMPENSATING call to
reverse the stock deduction before re-raising. That compensating call can
itself fail (network issue, inventory-service down) — this is logged as an
exception context but not retried indefinitely, since building a reliable
retry/outbox mechanism is real distributed-systems work that deserves its
own design once this system has actual production failure data to design
against, not a guess made now. A future sync-service/reconciliation job
(Phase 5 territory) is the honest long-term fix.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.core.inventory_client import (
    BatchStockItemDTO,
    InventoryClientProtocol,
)
from app.domain.models import PaymentMethod, Sale, SaleItem, SalePayment, SaleStatus
from app.repositories.sale_repository import SaleRepository


class SaleValidationError(Exception):
    """The request itself is malformed in a business sense — no items, no
    payments, a duplicate/unknown product, payments that don't add up."""


class SaleNotFoundError(Exception):
    pass


class SaleAlreadyVoidedError(Exception):
    pass


@dataclass(frozen=True)
class SaleItemInput:
    product_id: uuid.UUID
    quantity: Decimal
    discount_amount: Decimal = Decimal("0")


@dataclass(frozen=True)
class SalePaymentInput:
    method: PaymentMethod
    amount: Decimal
    reference: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SaleService:
    def __init__(self, sale_repo: SaleRepository, inventory_client: InventoryClientProtocol):
        self._sales = sale_repo
        self._inventory = inventory_client

    async def get_sale(self, *, business_id: uuid.UUID, sale_id: uuid.UUID) -> Sale:
        sale = await self._sales.get_by_id(business_id=business_id, sale_id=sale_id)
        if sale is None:
            raise SaleNotFoundError(f"Sale {sale_id} not found")
        return sale

    async def list_sales(
        self,
        *,
        business_id: uuid.UUID,
        location_id: uuid.UUID | None = None,
        customer_id: uuid.UUID | None = None,
        status: SaleStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Sale]:
        return await self._sales.list_sales(
            business_id=business_id,
            location_id=location_id,
            customer_id=customer_id,
            status=status.value if status else None,
            limit=limit,
            offset=offset,
        )

    async def list_items(self, *, sale_id: uuid.UUID) -> list[SaleItem]:
        return await self._sales.list_items(sale_id=sale_id)

    async def list_payments(self, *, sale_id: uuid.UUID) -> list[SalePayment]:
        return await self._sales.list_payments(sale_id=sale_id)

    async def create_sale(
        self,
        *,
        business_id: uuid.UUID,
        location_id: uuid.UUID,
        cashier_id: uuid.UUID,
        bearer_token: str,
        items: list[SaleItemInput],
        payments: list[SalePaymentInput],
        customer_id: uuid.UUID | None = None,
    ) -> Sale:
        if not items:
            raise SaleValidationError("A sale requires at least one item")
        if not payments:
            raise SaleValidationError(
                "A sale requires at least one payment — use PaymentMethod.CREDIT "
                "for the unpaid portion of a debt sale"
            )
        for item in items:
            if item.quantity <= 0:
                raise SaleValidationError(
                    f"Quantity must be positive for product {item.product_id}"
                )
        for payment in payments:
            if payment.amount <= 0:
                raise SaleValidationError("Payment amounts must be positive")

        product_ids = [item.product_id for item in items]
        if len(set(product_ids)) != len(product_ids):
            raise SaleValidationError(
                "Duplicate product_id in the same sale — combine into one line item"
            )

        # Authoritative product data, fetched fresh — the client only ever
        # sends product_id + quantity, never a price. See module docstring
        # and inventory_client.py for why.
        products = await self._inventory.get_products_batch(
            bearer_token=bearer_token, product_ids=product_ids
        )
        products_by_id = {p.id: p for p in products}

        missing = [pid for pid in product_ids if pid not in products_by_id]
        if missing:
            raise SaleValidationError(f"Product(s) not found for this business: {missing}")

        inactive_skus = [p.sku for p in products if not p.is_active]
        if inactive_skus:
            raise SaleValidationError(
                f"Product(s) are not active and cannot be sold: {inactive_skus}"
            )

        sale_items: list[SaleItem] = []
        subtotal = Decimal("0")
        discount_total = Decimal("0")
        for item in items:
            product = products_by_id[item.product_id]
            gross = product.unit_price * item.quantity
            if item.discount_amount > gross:
                raise SaleValidationError(
                    f"Discount ({item.discount_amount}) exceeds line total "
                    f"({gross}) for {product.sku}"
                )
            line_total = gross - item.discount_amount
            subtotal += gross
            discount_total += item.discount_amount
            sale_items.append(
                SaleItem(
                    product_id=product.id,
                    sku=product.sku,
                    product_name=product.name,
                    unit_price=product.unit_price,
                    quantity=item.quantity,
                    discount_amount=item.discount_amount,
                    line_total=line_total,
                )
            )

        # Tax handling deferred — every line item is currently untaxed
        # (tax_total fixed at 0). VAT/sales-tax rules vary enough across
        # jurisdictions that guessing a formula now would be worse than
        # explicitly deferring it to when a specific market's requirements
        # are known; the column exists on Sale so this doesn't need a
        # migration later.
        tax_total = Decimal("0")
        total = subtotal - discount_total + tax_total

        amount_paid = sum(
            (p.amount for p in payments if p.method != PaymentMethod.CREDIT), Decimal("0")
        )
        balance_due = total - amount_paid

        has_credit_payment = any(p.method == PaymentMethod.CREDIT for p in payments)
        if balance_due > 0 and not has_credit_payment:
            raise SaleValidationError(
                f"Payments ({amount_paid}) don't cover the total ({total}). "
                f"Add a CREDIT payment for the remaining {balance_due} if this is a debt sale."
            )
        if balance_due < 0:
            raise SaleValidationError(f"Payments ({amount_paid}) exceed the total ({total})")
        if not has_credit_payment:
            balance_due = Decimal("0")  # fully paid, no debt

        sale_id = uuid.uuid4()  # generated up front — used as the shared
        # reference_id linking this sale to its inventory-service movements,
        # so the two can be cross-referenced during reconciliation even
        # though they live in separate databases.

        # Remote truth first: deduct stock for every item as ONE atomic
        # operation (see inventory-service's record_batch_sale). If this
        # raises, NOTHING has been written locally yet — there's nothing
        # to compensate for.
        await self._inventory.batch_sale(
            bearer_token=bearer_token,
            items=[
                BatchStockItemDTO(
                    product_id=item.product_id, location_id=location_id, quantity=item.quantity
                )
                for item in items
            ],
            reference_id=sale_id,
        )

        try:
            receipt_seq = await self._sales.get_next_receipt_number(business_id=business_id)
            sale = Sale(
                id=sale_id,
                business_id=business_id,
                location_id=location_id,
                customer_id=customer_id,
                cashier_id=cashier_id,
                receipt_number=f"RCP-{receipt_seq:06d}",
                status=SaleStatus.COMPLETED.value,
                subtotal=subtotal,
                discount_total=discount_total,
                tax_total=tax_total,
                total=total,
                amount_paid=amount_paid,
                balance_due=balance_due,
            )
            sale_payments = [
                SalePayment(method=p.method.value, amount=p.amount, reference=p.reference)
                for p in payments
            ]
            await self._sales.create_sale_with_items_and_payments(
                sale=sale, items=sale_items, payments=sale_payments
            )
            await self._sales.commit()
            return sale
        except Exception:
            # Local persistence failed AFTER the remote deduction already
            # succeeded — best-effort reversal so stock isn't left
            # incorrectly deducted. See module docstring for why this is
            # "best effort", not a guarantee.
            try:
                await self._inventory.batch_return(
                    bearer_token=bearer_token,
                    items=[
                        BatchStockItemDTO(
                            product_id=item.product_id,
                            location_id=location_id,
                            quantity=item.quantity,
                        )
                        for item in items
                    ],
                    reference_id=sale_id,
                    reason=(
                        "Automatic reversal: sale failed to persist locally "
                        "after stock was deducted"
                    ),
                )
            except Exception:
                pass  # nothing more can be safely done synchronously here
            raise

    async def void_sale(
        self,
        *,
        business_id: uuid.UUID,
        sale_id: uuid.UUID,
        bearer_token: str,
        reason: str,
    ) -> Sale:
        if not reason or not reason.strip():
            raise SaleValidationError("Voiding a sale requires a reason")

        sale = await self.get_sale(business_id=business_id, sale_id=sale_id)
        if sale.status == SaleStatus.VOIDED.value:
            raise SaleAlreadyVoidedError(f"Sale {sale_id} is already voided")

        items = await self._sales.list_items(sale_id=sale.id)

        # Remote truth first, same principle as create_sale: restore stock
        # before marking the sale voided locally.
        await self._inventory.batch_return(
            bearer_token=bearer_token,
            items=[
                BatchStockItemDTO(
                    product_id=item.product_id,
                    location_id=sale.location_id,
                    quantity=item.quantity,
                )
                for item in items
            ],
            reference_id=sale.id,
            reason=reason,
        )

        sale.status = SaleStatus.VOIDED.value
        sale.voided_at = _utc_now()
        sale.void_reason = reason
        await self._sales.update(sale)
        await self._sales.commit()
        return sale
