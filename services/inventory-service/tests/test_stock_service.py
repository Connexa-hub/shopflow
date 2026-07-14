import uuid
from decimal import Decimal

import pytest

from app.domain.models import Location, MovementType, Product
from app.repositories.location_repository import LocationRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.stock_repository import StockRepository
from app.services.stock_service import (
    BatchStockItem,
    InsufficientStockError,
    InvalidStockReferenceError,
    StockService,
)


@pytest.fixture
async def business_id():
    return uuid.uuid4()


@pytest.fixture
async def product(db_session, business_id):
    repo = ProductRepository(db_session)
    product = Product(
        business_id=business_id,
        sku="SKU-001",
        name="Bag of Rice",
        unit="bag",
        unit_price=Decimal("25.00"),
        cost_price=Decimal("18.00"),
        low_stock_threshold=Decimal("5"),
    )
    created = await repo.create(product)
    await repo.commit()
    return created


@pytest.fixture
async def location(db_session, business_id):
    repo = LocationRepository(db_session)
    location = Location(business_id=business_id, name="Main Store", is_primary=True)
    created = await repo.create(location)
    await repo.commit()
    return created


@pytest.fixture
async def second_location(db_session, business_id):
    repo = LocationRepository(db_session)
    location = Location(business_id=business_id, name="Branch 2")
    created = await repo.create(location)
    await repo.commit()
    return created


@pytest.fixture
def stock_service(db_session):
    return StockService(
        StockRepository(db_session),
        ProductRepository(db_session),
        LocationRepository(db_session),
    )


class TestRestock:
    async def test_restock_increases_quantity_from_zero(
        self, stock_service, business_id, product, location
    ):
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product.id, location_id=location.id
        ) == Decimal("0")

        movement = await stock_service.record_restock(
            business_id=business_id,
            product_id=product.id,
            location_id=location.id,
            quantity=Decimal("100"),
        )

        assert movement.movement_type == MovementType.RESTOCK.value
        assert movement.quantity_delta == Decimal("100")
        assert movement.resulting_quantity == Decimal("100")
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product.id, location_id=location.id
        ) == Decimal("100")

    async def test_restock_rejects_non_positive_quantity(
        self, stock_service, business_id, product, location
    ):
        with pytest.raises(ValueError):
            await stock_service.record_restock(
                business_id=business_id,
                product_id=product.id,
                location_id=location.id,
                quantity=Decimal("0"),
            )


class TestSale:
    async def test_sale_decreases_quantity(self, stock_service, business_id, product, location):
        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("50")
        )
        movement = await stock_service.record_sale(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("12")
        )

        assert movement.quantity_delta == Decimal("-12")
        assert movement.resulting_quantity == Decimal("38")
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product.id, location_id=location.id
        ) == Decimal("38")

    async def test_sale_fails_when_insufficient_stock(
        self, stock_service, business_id, product, location
    ):
        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("5")
        )

        with pytest.raises(InsufficientStockError):
            await stock_service.record_sale(
                business_id=business_id,
                product_id=product.id,
                location_id=location.id,
                quantity=Decimal("10"),
            )

        # Quantity must be UNCHANGED after a rejected sale — this is the
        # core correctness property of the ledger.
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product.id, location_id=location.id
        ) == Decimal("5")

    async def test_sale_on_never_stocked_product_fails(
        self, stock_service, business_id, product, location
    ):
        with pytest.raises(InsufficientStockError):
            await stock_service.record_sale(
                business_id=business_id,
                product_id=product.id,
                location_id=location.id,
                quantity=Decimal("1"),
            )


class TestAdjustment:
    async def test_positive_adjustment(self, stock_service, business_id, product, location):
        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("10")
        )
        movement = await stock_service.record_adjustment(
            business_id=business_id,
            product_id=product.id,
            location_id=location.id,
            quantity_delta=Decimal("3"),
            reason="Found extra stock during count",
        )
        assert movement.resulting_quantity == Decimal("13")

    async def test_negative_adjustment(self, stock_service, business_id, product, location):
        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("10")
        )
        movement = await stock_service.record_adjustment(
            business_id=business_id,
            product_id=product.id,
            location_id=location.id,
            quantity_delta=Decimal("-4"),
            reason="Damaged during count",
        )
        assert movement.resulting_quantity == Decimal("6")

    async def test_adjustment_requires_reason(self, stock_service, business_id, product, location):
        with pytest.raises(ValueError):
            await stock_service.record_adjustment(
                business_id=business_id,
                product_id=product.id,
                location_id=location.id,
                quantity_delta=Decimal("1"),
                reason="   ",
            )


class TestWaste:
    async def test_waste_decreases_quantity_and_requires_reason(
        self, stock_service, business_id, product, location
    ):
        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("10")
        )
        movement = await stock_service.record_waste(
            business_id=business_id,
            product_id=product.id,
            location_id=location.id,
            quantity=Decimal("2"),
            reason="Spoiled",
        )
        assert movement.resulting_quantity == Decimal("8")

        with pytest.raises(ValueError):
            await stock_service.record_waste(
                business_id=business_id,
                product_id=product.id,
                location_id=location.id,
                quantity=Decimal("1"),
                reason="",
            )


class TestTransfer:
    async def test_transfer_moves_quantity_between_locations(
        self, stock_service, business_id, product, location, second_location
    ):
        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("20")
        )

        out_movement, in_movement = await stock_service.transfer(
            business_id=business_id,
            product_id=product.id,
            from_location_id=location.id,
            to_location_id=second_location.id,
            quantity=Decimal("7"),
        )

        assert out_movement.quantity_delta == Decimal("-7")
        assert in_movement.quantity_delta == Decimal("7")
        assert out_movement.reference_id == in_movement.reference_id  # correlated pair

        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product.id, location_id=location.id
        ) == Decimal("13")
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product.id, location_id=second_location.id
        ) == Decimal("7")

    async def test_transfer_fails_with_insufficient_source_stock(
        self, stock_service, business_id, product, location, second_location
    ):
        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("3")
        )
        with pytest.raises(InsufficientStockError):
            await stock_service.transfer(
                business_id=business_id,
                product_id=product.id,
                from_location_id=location.id,
                to_location_id=second_location.id,
                quantity=Decimal("10"),
            )
        # Destination must receive nothing if the source leg failed.
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product.id, location_id=second_location.id
        ) == Decimal("0")

    async def test_transfer_rejects_same_location(
        self, stock_service, business_id, product, location
    ):
        with pytest.raises(ValueError):
            await stock_service.transfer(
                business_id=business_id,
                product_id=product.id,
                from_location_id=location.id,
                to_location_id=location.id,
                quantity=Decimal("1"),
            )


class TestMovementHistory:
    async def test_movements_listed_most_recent_first(
        self, stock_service, business_id, product, location
    ):
        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("10")
        )
        await stock_service.record_sale(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("3")
        )
        movements = await stock_service.list_movements(business_id=business_id, product_id=product.id)
        assert len(movements) == 2
        # Most recent (the sale) first.
        assert movements[0].movement_type == MovementType.SALE.value
        assert movements[1].movement_type == MovementType.RESTOCK.value


class TestLowStock:
    async def test_low_stock_query_returns_items_at_or_below_threshold(
        self, stock_service, business_id, product, location
    ):
        # product.low_stock_threshold == 5 (see fixture)
        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("3")
        )
        results = await stock_service.list_low_stock(business_id=business_id)
        assert len(results) == 1
        level, returned_product = results[0]
        assert returned_product.id == product.id
        assert level.quantity == Decimal("3")

    async def test_low_stock_excludes_well_stocked_items(
        self, stock_service, business_id, product, location
    ):
        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("50")
        )
        results = await stock_service.list_low_stock(business_id=business_id)
        assert results == []


class TestTenantIsolation:
    """The gap found on review: nothing previously checked that product_id/
    location_id passed into StockService actually belonged to the calling
    business_id. These tests exist specifically to catch a regression of
    that bug, not just to test happy-path behavior."""

    async def test_cannot_record_movement_for_another_businesss_product(
        self, stock_service, db_session, location
    ):
        other_business_id = uuid.uuid4()
        other_product = Product(
            business_id=other_business_id,
            sku="OTHER-001",
            name="Someone Else's Product",
            unit_price=Decimal("10.00"),
        )
        repo = ProductRepository(db_session)
        created = await repo.create(other_product)
        await repo.commit()

        # `location` belongs to a DIFFERENT business than `other_product`.
        # Neither business_id matches the product's actual owner.
        with pytest.raises(InvalidStockReferenceError):
            await stock_service.record_restock(
                business_id=uuid.uuid4(),  # a third, unrelated business
                product_id=created.id,
                location_id=location.id,
                quantity=Decimal("10"),
            )

    async def test_cannot_read_quantity_for_another_businesss_product(
        self, stock_service, business_id, product, location
    ):
        with pytest.raises(InvalidStockReferenceError):
            await stock_service.get_current_quantity(
                business_id=uuid.uuid4(),  # wrong business
                product_id=product.id,
                location_id=location.id,
            )

    async def test_cannot_use_own_product_with_anothers_location(
        self, stock_service, db_session, business_id, product
    ):
        other_business_id = uuid.uuid4()
        other_location = Location(business_id=other_business_id, name="Not Yours")
        repo = LocationRepository(db_session)
        created = await repo.create(other_location)
        await repo.commit()

        with pytest.raises(InvalidStockReferenceError):
            await stock_service.record_restock(
                business_id=business_id,  # correct for `product`...
                product_id=product.id,
                location_id=created.id,  # ...but NOT for this location
                quantity=Decimal("10"),
            )


class TestReturn:
    async def test_return_increases_quantity(self, stock_service, business_id, product, location):
        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("10")
        )
        await stock_service.record_sale(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("3")
        )
        movement = await stock_service.record_return(
            business_id=business_id,
            product_id=product.id,
            location_id=location.id,
            quantity=Decimal("3"),
            reason="Customer changed their mind",
        )
        assert movement.movement_type == MovementType.RETURN.value
        assert movement.quantity_delta == Decimal("3")
        assert movement.resulting_quantity == Decimal("10")

    async def test_return_rejects_non_positive_quantity(
        self, stock_service, business_id, product, location
    ):
        with pytest.raises(ValueError):
            await stock_service.record_return(
                business_id=business_id,
                product_id=product.id,
                location_id=location.id,
                quantity=Decimal("0"),
            )


class TestBatchSale:
    async def test_batch_sale_deducts_all_items_atomically(
        self, stock_service, db_session, business_id, location
    ):
        repo = ProductRepository(db_session)
        product_a = await repo.create(
            Product(business_id=business_id, sku="A", name="A", unit_price=Decimal("1"))
        )
        product_b = await repo.create(
            Product(business_id=business_id, sku="B", name="B", unit_price=Decimal("1"))
        )
        await repo.commit()

        await stock_service.record_restock(
            business_id=business_id, product_id=product_a.id, location_id=location.id, quantity=Decimal("10")
        )
        await stock_service.record_restock(
            business_id=business_id, product_id=product_b.id, location_id=location.id, quantity=Decimal("10")
        )

        movements = await stock_service.record_batch_sale(
            business_id=business_id,
            items=[
                BatchStockItem(product_id=product_a.id, location_id=location.id, quantity=Decimal("4")),
                BatchStockItem(product_id=product_b.id, location_id=location.id, quantity=Decimal("6")),
            ],
        )
        assert len(movements) == 2
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product_a.id, location_id=location.id
        ) == Decimal("6")
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product_b.id, location_id=location.id
        ) == Decimal("4")

        # Both movements share one reference_id, correlating them as one checkout.
        assert movements[0].reference_id == movements[1].reference_id

    async def test_batch_sale_is_all_or_nothing(
        self, stock_service, db_session, business_id, location
    ):
        """The core atomicity property: if item 2 of 2 has insufficient
        stock, item 1's deduction must NOT be left applied."""
        repo = ProductRepository(db_session)
        product_a = await repo.create(
            Product(business_id=business_id, sku="A2", name="A2", unit_price=Decimal("1"))
        )
        product_b = await repo.create(
            Product(business_id=business_id, sku="B2", name="B2", unit_price=Decimal("1"))
        )
        await repo.commit()

        await stock_service.record_restock(
            business_id=business_id, product_id=product_a.id, location_id=location.id, quantity=Decimal("10")
        )
        # product_b has ZERO stock — this item will fail the insufficient-stock check.

        with pytest.raises(InsufficientStockError):
            await stock_service.record_batch_sale(
                business_id=business_id,
                items=[
                    BatchStockItem(product_id=product_a.id, location_id=location.id, quantity=Decimal("4")),
                    BatchStockItem(product_id=product_b.id, location_id=location.id, quantity=Decimal("1")),
                ],
            )

        # product_a's stock must be UNCHANGED — nothing commits until the
        # whole batch succeeds.
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product_a.id, location_id=location.id
        ) == Decimal("10")

    async def test_batch_sale_rejects_empty_items(self, stock_service, business_id):
        with pytest.raises(ValueError):
            await stock_service.record_batch_sale(business_id=business_id, items=[])


class TestBatchReturn:
    async def test_batch_return_restores_all_items(
        self, stock_service, db_session, business_id, location
    ):
        repo = ProductRepository(db_session)
        product_a = await repo.create(
            Product(business_id=business_id, sku="RA", name="RA", unit_price=Decimal("1"))
        )
        product_b = await repo.create(
            Product(business_id=business_id, sku="RB", name="RB", unit_price=Decimal("1"))
        )
        await repo.commit()

        await stock_service.record_restock(
            business_id=business_id, product_id=product_a.id, location_id=location.id, quantity=Decimal("10")
        )
        await stock_service.record_restock(
            business_id=business_id, product_id=product_b.id, location_id=location.id, quantity=Decimal("10")
        )
        await stock_service.record_batch_sale(
            business_id=business_id,
            items=[
                BatchStockItem(product_id=product_a.id, location_id=location.id, quantity=Decimal("4")),
                BatchStockItem(product_id=product_b.id, location_id=location.id, quantity=Decimal("6")),
            ],
        )

        await stock_service.record_batch_return(
            business_id=business_id,
            items=[
                BatchStockItem(product_id=product_a.id, location_id=location.id, quantity=Decimal("4")),
                BatchStockItem(product_id=product_b.id, location_id=location.id, quantity=Decimal("6")),
            ],
            reason="Sale voided",
        )

        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product_a.id, location_id=location.id
        ) == Decimal("10")
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product_b.id, location_id=location.id
        ) == Decimal("10")


class TestTransferAtomicity:
    async def test_transfer_commits_both_legs_together(
        self, stock_service, business_id, product, location, second_location
    ):
        """Regression test for a bug found on review: the original
        transfer() called record_movement (which commits) for each leg
        independently, so a failure on the second leg could leave the
        first already committed with no matching credit at the
        destination. Now both legs share one commit."""
        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("20")
        )
        out_movement, in_movement = await stock_service.transfer(
            business_id=business_id,
            product_id=product.id,
            from_location_id=location.id,
            to_location_id=second_location.id,
            quantity=Decimal("5"),
        )
        # Both movements exist and are correctly linked post-commit.
        assert out_movement.reference_id == in_movement.reference_id
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product.id, location_id=location.id
        ) == Decimal("15")
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product.id, location_id=second_location.id
        ) == Decimal("5")

    async def test_transfer_rolls_back_first_leg_when_second_leg_fails(
        self, stock_service, db_session, business_id, product, location
    ):
        """Regression test for the real bug this class's first test didn't
        actually catch: that test's insufficient-stock scenario fails on
        the FIRST leg, before any writes happen — it never exercised "leg
        one succeeds with real uncommitted writes, then leg two fails".
        This does: leg one (OUT) has enough stock and genuinely applies;
        leg two (IN) fails because `to_location_id` belongs to a
        different business. Without an explicit rollback, leg one's
        uncommitted UPDATE stays visible to this same session even though
        it was never meant to be permanent — which is exactly the bug a
        previous version of this method had (see record_batch_sale's
        near-identical bug, caught by test_batch_sale_is_all_or_nothing)."""
        other_business_location = Location(business_id=uuid.uuid4(), name="Not Yours")
        repo = LocationRepository(db_session)
        invalid_destination = await repo.create(other_business_location)
        await repo.commit()

        await stock_service.record_restock(
            business_id=business_id, product_id=product.id, location_id=location.id, quantity=Decimal("20")
        )

        with pytest.raises(InvalidStockReferenceError):
            await stock_service.transfer(
                business_id=business_id,
                product_id=product.id,
                from_location_id=location.id,
                to_location_id=invalid_destination.id,
                quantity=Decimal("5"),
            )

        # The OUT leg must be fully rolled back — quantity unchanged.
        assert await stock_service.get_current_quantity(
            business_id=business_id, product_id=product.id, location_id=location.id
        ) == Decimal("20")
