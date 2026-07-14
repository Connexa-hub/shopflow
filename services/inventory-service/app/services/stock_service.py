"""
Business logic for the stock ledger. This is the module that answers
"how much stock do we have" and "what happened to it" for every product at
every location, and it's the one place in the service where getting the
arithmetic wrong means a shop owner's numbers stop matching reality.

Tenant-ownership check (fixed after review — was missing entirely): every
public method here takes a `business_id` and verifies BOTH `product_id`
and `location_id` actually belong to that business before touching
anything. Without this, a valid token from Business A could read or write
stock for Business B's product/location UUIDs directly — there's no
ORM relationship or DB-level cross-check to catch this otherwise, since
`business_id` on StockMovement/StockLevel records the movement's own
tenant but was never being compared against the *referenced* product's and
location's actual owning tenant.

Concurrency note (documented honestly rather than silently assumed away):
the insufficient-stock check reads the current quantity, computes the
prospective result in Python, and only then issues the atomic UPDATE. The
UPDATE itself is safe under concurrency (see StockRepository), but the
*validation* is optimistic: under heavy concurrent load, two simultaneous
sales could both pass the check against a stale read before either
commits, allowing stock to go negative in a narrow race window. The ledger
itself would still be internally consistent (every movement recorded,
every resulting_quantity accurate for its own transaction), just
potentially negative. Hardening this further (e.g. a CHECK constraint plus
retry-on-conflict, or a Postgres-only SELECT...FOR UPDATE path) is still
deferred, now that sales-service (Phase 3) exists and is the first real
caller — the decision was gated on knowing real concurrent load patterns,
not merely on sales-service existing, and a handful of businesses running
this for the first time won't yet produce that signal.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import NamedTuple

from app.domain.models import MovementType, Product, StockLevel, StockMovement
from app.repositories.location_repository import LocationRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.stock_repository import StockRepository


class BatchStockItem(NamedTuple):
    """One line item in a multi-item stock operation (a checkout's cart, or
    the items being reversed when voiding one). Kept separate from any
    API schema — this is the service-layer shape; sales-service's request
    schema maps onto this, not the other way around."""

    product_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal


class InsufficientStockError(Exception):
    pass


class InvalidStockReferenceError(Exception):
    """Raised when a product_id or location_id doesn't belong to the
    calling business — either it doesn't exist, or it belongs to someone
    else's tenant. Deliberately doesn't distinguish the two in the message
    (same as auth returning one generic "invalid credentials" message)
    so the API can't be used to enumerate other businesses' valid IDs."""


class StockService:
    def __init__(
        self,
        stock_repo: StockRepository,
        product_repo: ProductRepository,
        location_repo: LocationRepository,
        *,
        allow_negative_stock: bool = False,
    ):
        self._stock = stock_repo
        self._products = product_repo
        self._locations = location_repo
        self._allow_negative_stock = allow_negative_stock

    async def _verify_ownership(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        location_id: uuid.UUID | None,
    ) -> None:
        product = await self._products.get_by_id(business_id=business_id, product_id=product_id)
        if product is None:
            raise InvalidStockReferenceError(f"Product {product_id} not found for this business")
        if location_id is not None:
            location = await self._locations.get_by_id(
                business_id=business_id, location_id=location_id
            )
            if location is None:
                raise InvalidStockReferenceError(
                    f"Location {location_id} not found for this business"
                )

    async def get_current_quantity(
        self, *, business_id: uuid.UUID, product_id: uuid.UUID, location_id: uuid.UUID
    ) -> Decimal:
        await self._verify_ownership(
            business_id=business_id, product_id=product_id, location_id=location_id
        )
        level = await self._stock.get_stock_level(product_id=product_id, location_id=location_id)
        return level.quantity if level else Decimal("0")

    async def _apply_movement(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        location_id: uuid.UUID,
        movement_type: MovementType,
        quantity_delta: Decimal,
        reference_type: str | None = None,
        reference_id: uuid.UUID | None = None,
        reason: str | None = None,
        created_by: uuid.UUID | None = None,
    ) -> StockMovement:
        """Does everything record_movement does — ownership check,
        insufficient-stock check, atomic quantity update, ledger row —
        EXCEPT commit. Exists so a caller processing several movements as
        one logical operation (a multi-item sale, a branch transfer, a
        multi-item return) can commit ONCE at the end, making the whole
        group atomic: if item 3 of 5 fails, items 1-2's uncommitted changes
        roll back too when the session closes without a commit, rather
        than being left half-applied. Single-movement callers
        (record_restock, record_sale, etc.) still commit immediately via
        record_movement — this method is the shared core, not a new public
        entry point on its own."""
        await self._verify_ownership(
            business_id=business_id, product_id=product_id, location_id=location_id
        )

        level = await self._stock.get_stock_level(product_id=product_id, location_id=location_id)
        current_quantity = level.quantity if level else Decimal("0")
        prospective_quantity = current_quantity + quantity_delta

        if prospective_quantity < 0 and not self._allow_negative_stock:
            raise InsufficientStockError(
                f"Cannot apply a change of {quantity_delta} to product {product_id} "
                f"at location {location_id}: only {current_quantity} currently in stock."
            )

        if level is None:
            await self._stock.create_stock_level(
                business_id=business_id, product_id=product_id, location_id=location_id
            )

        resulting_quantity = await self._stock.apply_quantity_delta(
            product_id=product_id, location_id=location_id, delta=quantity_delta
        )

        movement = StockMovement(
            business_id=business_id,
            product_id=product_id,
            location_id=location_id,
            movement_type=movement_type.value,
            quantity_delta=quantity_delta,
            resulting_quantity=resulting_quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            reason=reason,
            created_by=created_by,
        )
        await self._stock.create_movement(movement)
        return movement

    async def record_movement(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        location_id: uuid.UUID,
        movement_type: MovementType,
        quantity_delta: Decimal,
        reference_type: str | None = None,
        reference_id: uuid.UUID | None = None,
        reason: str | None = None,
        created_by: uuid.UUID | None = None,
    ) -> StockMovement:
        # The common failure (InsufficientStockError) raises inside
        # _apply_movement before any write happens, so there's usually
        # nothing to undo — but if this is the first-ever movement for a
        # product/location pair, create_stock_level() has already flushed
        # a new row before a LATER, unrelated failure could occur. Same
        # explicit rollback as the batch/transfer methods, for the same
        # reason: atomicity shouldn't depend on the caller's session
        # discipline.
        try:
            movement = await self._apply_movement(
                business_id=business_id,
                product_id=product_id,
                location_id=location_id,
                movement_type=movement_type,
                quantity_delta=quantity_delta,
                reference_type=reference_type,
                reference_id=reference_id,
                reason=reason,
                created_by=created_by,
            )
        except Exception:
            await self._stock.rollback()
            raise

        await self._stock.commit()
        return movement

    async def record_restock(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        location_id: uuid.UUID,
        quantity: Decimal,
        reference_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
    ) -> StockMovement:
        if quantity <= 0:
            raise ValueError("Restock quantity must be positive")
        return await self.record_movement(
            business_id=business_id,
            product_id=product_id,
            location_id=location_id,
            movement_type=MovementType.RESTOCK,
            quantity_delta=quantity,
            reference_type="purchase",
            reference_id=reference_id,
            created_by=created_by,
        )

    async def record_sale(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        location_id: uuid.UUID,
        quantity: Decimal,
        reference_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
    ) -> StockMovement:
        if quantity <= 0:
            raise ValueError("Sale quantity must be positive")
        return await self.record_movement(
            business_id=business_id,
            product_id=product_id,
            location_id=location_id,
            movement_type=MovementType.SALE,
            quantity_delta=-quantity,
            reference_type="sale",
            reference_id=reference_id,
            created_by=created_by,
        )

    async def record_adjustment(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        location_id: uuid.UUID,
        quantity_delta: Decimal,
        reason: str,
        created_by: uuid.UUID | None = None,
    ) -> StockMovement:
        """Manual correction, e.g. after a physical stock count. Can be
        positive (found more than the system thought) or negative
        (found less). `reason` is required — an unexplained adjustment is
        exactly the kind of thing an owner will ask about later."""
        if not reason or not reason.strip():
            raise ValueError("An adjustment requires a reason")
        return await self.record_movement(
            business_id=business_id,
            product_id=product_id,
            location_id=location_id,
            movement_type=MovementType.ADJUSTMENT,
            quantity_delta=quantity_delta,
            reason=reason,
            created_by=created_by,
        )

    async def record_waste(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        location_id: uuid.UUID,
        quantity: Decimal,
        reason: str,
        created_by: uuid.UUID | None = None,
    ) -> StockMovement:
        if quantity <= 0:
            raise ValueError("Waste quantity must be positive")
        if not reason or not reason.strip():
            raise ValueError("Recording waste requires a reason")
        return await self.record_movement(
            business_id=business_id,
            product_id=product_id,
            location_id=location_id,
            movement_type=MovementType.WASTE,
            quantity_delta=-quantity,
            reason=reason,
            created_by=created_by,
        )

    async def transfer(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        from_location_id: uuid.UUID,
        to_location_id: uuid.UUID,
        quantity: Decimal,
        created_by: uuid.UUID | None = None,
    ) -> tuple[StockMovement, StockMovement]:
        """Moves stock between two branches of the same business. Both legs
        share a `reference_id` (the transfer's own id) so they can be
        correlated in the ledger later, and commit together as ONE
        transaction (fixed on Phase 2 review — the first version committed
        each leg via record_movement independently, so a failure on the
        second leg for any reason would have left the source already
        debited with no matching credit at the destination).

        Explicitly rolls back on failure rather than assuming the caller
        will discard the session (fixed after a test caught this: the
        original comment here claimed the uncommitted first leg would
        "roll back when the session closes" — true only if something
        actually closes/rolls back the session before it's queried again.
        A caller that reuses one long-lived session across multiple
        operations — a Celery worker, or simply two calls in the same test
        — would otherwise see the first leg's uncommitted change via that
        same session's own read-your-writes visibility, without it ever
        being durably persisted. Atomicity should be a property of this
        method, not an accident of caller session-lifecycle discipline.)
        """
        if quantity <= 0:
            raise ValueError("Transfer quantity must be positive")
        if from_location_id == to_location_id:
            raise ValueError("Cannot transfer stock to the same location")

        transfer_id = uuid.uuid4()

        try:
            out_movement = await self._apply_movement(
                business_id=business_id,
                product_id=product_id,
                location_id=from_location_id,
                movement_type=MovementType.TRANSFER_OUT,
                quantity_delta=-quantity,
                reference_type="transfer",
                reference_id=transfer_id,
                created_by=created_by,
            )
            in_movement = await self._apply_movement(
                business_id=business_id,
                product_id=product_id,
                location_id=to_location_id,
                movement_type=MovementType.TRANSFER_IN,
                quantity_delta=quantity,
                reference_type="transfer",
                reference_id=transfer_id,
                created_by=created_by,
            )
        except Exception:
            await self._stock.rollback()
            raise

        await self._stock.commit()
        return out_movement, in_movement

    async def record_return(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        location_id: uuid.UUID,
        quantity: Decimal,
        reference_id: uuid.UUID | None = None,
        reason: str | None = None,
        created_by: uuid.UUID | None = None,
    ) -> StockMovement:
        """Stock coming BACK in — a voided/refunded sale, or a customer
        return. Positive delta, same shape as record_restock but a
        distinct movement_type so the ledger can tell "we bought more
        stock" apart from "a sale was undone" when an owner reviews
        history."""
        if quantity <= 0:
            raise ValueError("Return quantity must be positive")
        return await self.record_movement(
            business_id=business_id,
            product_id=product_id,
            location_id=location_id,
            movement_type=MovementType.RETURN,
            quantity_delta=quantity,
            reference_type="return",
            reference_id=reference_id,
            reason=reason,
            created_by=created_by,
        )

    async def record_batch_sale(
        self,
        *,
        business_id: uuid.UUID,
        items: list[BatchStockItem],
        reference_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
    ) -> list[StockMovement]:
        """Deducts stock for several line items as ONE atomic operation —
        a multi-item checkout must never partially apply (sell items 1-2,
        then discover item 3 is out of stock and leave 1-2 already
        deducted). All items are checked and applied via _apply_movement
        (no per-item commit), and an explicit rollback runs if any item
        fails partway through (see transfer()'s docstring for why this is
        an explicit try/except rather than an assumption that the caller
        will discard the session — a real bug caught by a test that reused
        one session across a whole test case, exactly the kind of caller
        this needs to be robust against). This is what sales-service
        (Phase 3) calls for `POST /stock/batch-sale` — see that route for
        the cross-service contract."""
        if not items:
            raise ValueError("Batch sale requires at least one item")

        batch_reference_id = reference_id or uuid.uuid4()
        movements = []
        try:
            for item in items:
                if item.quantity <= 0:
                    raise ValueError(f"Quantity must be positive for product {item.product_id}")
                movement = await self._apply_movement(
                    business_id=business_id,
                    product_id=item.product_id,
                    location_id=item.location_id,
                    movement_type=MovementType.SALE,
                    quantity_delta=-item.quantity,
                    reference_type="sale",
                    reference_id=batch_reference_id,
                    created_by=created_by,
                )
                movements.append(movement)
        except Exception:
            await self._stock.rollback()
            raise

        await self._stock.commit()
        return movements

    async def record_batch_return(
        self,
        *,
        business_id: uuid.UUID,
        items: list[BatchStockItem],
        reference_id: uuid.UUID | None = None,
        reason: str | None = None,
        created_by: uuid.UUID | None = None,
    ) -> list[StockMovement]:
        """The reverse of record_batch_sale — used when voiding a
        multi-item sale, so every line item's stock is restored as one
        atomic operation rather than reversed one at a time. Same explicit
        rollback-on-failure as record_batch_sale/transfer."""
        if not items:
            raise ValueError("Batch return requires at least one item")

        batch_reference_id = reference_id or uuid.uuid4()
        movements = []
        try:
            for item in items:
                if item.quantity <= 0:
                    raise ValueError(f"Quantity must be positive for product {item.product_id}")
                movement = await self._apply_movement(
                    business_id=business_id,
                    product_id=item.product_id,
                    location_id=item.location_id,
                    movement_type=MovementType.RETURN,
                    quantity_delta=item.quantity,
                    reference_type="return",
                    reference_id=batch_reference_id,
                    reason=reason,
                    created_by=created_by,
                )
                movements.append(movement)
        except Exception:
            await self._stock.rollback()
            raise

        await self._stock.commit()
        return movements

    async def list_movements(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        location_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[StockMovement]:
        await self._verify_ownership(
            business_id=business_id, product_id=product_id, location_id=location_id
        )
        return await self._stock.list_movements(
            product_id=product_id, location_id=location_id, limit=limit
        )

    async def list_low_stock(
        self, *, business_id: uuid.UUID, location_id: uuid.UUID | None = None
    ) -> list[tuple[StockLevel, Product]]:
        return await self._stock.list_low_stock(business_id=business_id, location_id=location_id)
