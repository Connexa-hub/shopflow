import uuid
from decimal import Decimal

import pytest

from app.domain.models import Location, MovementType, Product
from app.repositories.location_repository import LocationRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.stock_repository import StockRepository
from app.services.stock_service import (
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
