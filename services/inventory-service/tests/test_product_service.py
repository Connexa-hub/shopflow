import uuid
from decimal import Decimal

import pytest

from app.domain.models import Category, Supplier
from app.repositories.category_repository import CategoryRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.supplier_repository import SupplierRepository
from app.services.product_service import (
    DuplicateBarcodeError,
    DuplicateSKUError,
    InvalidProductReferenceError,
    ProductNotFoundError,
    ProductService,
)


@pytest.fixture
def product_service(db_session):
    return ProductService(
        ProductRepository(db_session),
        CategoryRepository(db_session),
        SupplierRepository(db_session),
    )


class TestCreateProduct:
    async def test_creates_product(self, product_service):
        business_id = uuid.uuid4()
        product = await product_service.create_product(
            business_id=business_id,
            sku="RICE-50KG",
            name="Rice 50kg Bag",
            unit_price=Decimal("45000.00"),
            barcode="6001234567890",
        )
        assert product.sku == "RICE-50KG"
        assert product.barcode == "6001234567890"
        assert product.is_active is True

    async def test_rejects_duplicate_sku_same_business(self, product_service):
        business_id = uuid.uuid4()
        await product_service.create_product(
            business_id=business_id, sku="DUP-1", name="First", unit_price=Decimal("10")
        )
        with pytest.raises(DuplicateSKUError):
            await product_service.create_product(
                business_id=business_id, sku="DUP-1", name="Second", unit_price=Decimal("20")
            )

    async def test_rejects_duplicate_barcode_same_business(self, product_service):
        business_id = uuid.uuid4()
        await product_service.create_product(
            business_id=business_id,
            sku="A",
            name="First",
            unit_price=Decimal("10"),
            barcode="111",
        )
        with pytest.raises(DuplicateBarcodeError):
            await product_service.create_product(
                business_id=business_id,
                sku="B",
                name="Second",
                unit_price=Decimal("20"),
                barcode="111",
            )

    async def test_same_sku_allowed_across_different_businesses(self, product_service):
        """Tenant isolation: two unrelated merchants both using 'SKU-001'
        must never collide. This is the property the UniqueConstraint on
        (business_id, sku) — not a bare unique on sku — exists to guarantee."""
        business_a = uuid.uuid4()
        business_b = uuid.uuid4()

        product_a = await product_service.create_product(
            business_id=business_a, sku="SKU-001", name="Business A's Product", unit_price=Decimal("10")
        )
        product_b = await product_service.create_product(
            business_id=business_b, sku="SKU-001", name="Business B's Product", unit_price=Decimal("99")
        )

        assert product_a.id != product_b.id
        assert product_a.business_id == business_a
        assert product_b.business_id == business_b


class TestTenantIsolation:
    async def test_list_products_never_returns_another_businesss_products(self, product_service):
        business_a = uuid.uuid4()
        business_b = uuid.uuid4()

        await product_service.create_product(
            business_id=business_a, sku="A-1", name="A Product", unit_price=Decimal("1")
        )
        await product_service.create_product(
            business_id=business_b, sku="B-1", name="B Product", unit_price=Decimal("1")
        )

        a_products = await product_service.list_products(business_id=business_a)
        assert len(a_products) == 1
        assert a_products[0].sku == "A-1"

    async def test_get_product_scoped_to_business_returns_not_found_for_other_business(
        self, product_service
    ):
        business_a = uuid.uuid4()
        business_b = uuid.uuid4()

        product = await product_service.create_product(
            business_id=business_a, sku="X-1", name="X Product", unit_price=Decimal("1")
        )

        with pytest.raises(ProductNotFoundError):
            await product_service.get_product(business_id=business_b, product_id=product.id)


class TestBarcodeLookup:
    async def test_get_by_barcode(self, product_service):
        business_id = uuid.uuid4()
        await product_service.create_product(
            business_id=business_id,
            sku="Y-1",
            name="Scannable Product",
            unit_price=Decimal("5"),
            barcode="9990001112223",
        )
        found = await product_service.get_by_barcode(
            business_id=business_id, barcode="9990001112223"
        )
        assert found.sku == "Y-1"

    async def test_get_by_unknown_barcode_raises(self, product_service):
        with pytest.raises(ProductNotFoundError):
            await product_service.get_by_barcode(business_id=uuid.uuid4(), barcode="does-not-exist")


class TestUpdateProduct:
    async def test_updates_allowed_fields(self, product_service):
        business_id = uuid.uuid4()
        product = await product_service.create_product(
            business_id=business_id, sku="U-1", name="Old Name", unit_price=Decimal("10")
        )
        updated = await product_service.update_product(
            business_id=business_id, product_id=product.id, name="New Name", unit_price=Decimal("15")
        )
        assert updated.name == "New Name"
        assert updated.unit_price == Decimal("15")

    async def test_update_rejects_sku_collision_with_another_product(self, product_service):
        business_id = uuid.uuid4()
        await product_service.create_product(
            business_id=business_id, sku="TAKEN", name="First", unit_price=Decimal("1")
        )
        second = await product_service.create_product(
            business_id=business_id, sku="FREE", name="Second", unit_price=Decimal("1")
        )
        with pytest.raises(DuplicateSKUError):
            await product_service.update_product(
                business_id=business_id, product_id=second.id, sku="TAKEN"
            )


class TestCategoryAndSupplierOwnership:
    """Regression coverage for a gap found on review: create_product and
    update_product accepted category_id/supplier_id without checking they
    belonged to the same business — the same class of cross-tenant bug
    fixed in StockService, just for the product catalog instead of stock."""

    async def test_create_product_with_own_category_succeeds(self, db_session, product_service):
        business_id = uuid.uuid4()
        category = Category(business_id=business_id, name="Beverages")
        cat_repo = CategoryRepository(db_session)
        created_category = await cat_repo.create(category)
        await cat_repo.commit()

        product = await product_service.create_product(
            business_id=business_id,
            sku="BEV-1",
            name="Cola",
            unit_price=Decimal("2.00"),
            category_id=created_category.id,
        )
        assert product.category_id == created_category.id

    async def test_create_product_rejects_another_businesss_category(
        self, db_session, product_service
    ):
        other_business_id = uuid.uuid4()
        category = Category(business_id=other_business_id, name="Not Yours")
        cat_repo = CategoryRepository(db_session)
        created_category = await cat_repo.create(category)
        await cat_repo.commit()

        with pytest.raises(InvalidProductReferenceError):
            await product_service.create_product(
                business_id=uuid.uuid4(),  # different business than the category
                sku="BEV-2",
                name="Cola",
                unit_price=Decimal("2.00"),
                category_id=created_category.id,
            )

    async def test_create_product_rejects_another_businesss_supplier(
        self, db_session, product_service
    ):
        other_business_id = uuid.uuid4()
        supplier = Supplier(business_id=other_business_id, name="Not Your Supplier")
        sup_repo = SupplierRepository(db_session)
        created_supplier = await sup_repo.create(supplier)
        await sup_repo.commit()

        with pytest.raises(InvalidProductReferenceError):
            await product_service.create_product(
                business_id=uuid.uuid4(),
                sku="BEV-3",
                name="Cola",
                unit_price=Decimal("2.00"),
                supplier_id=created_supplier.id,
            )

    async def test_update_product_rejects_reassigning_to_anothers_category(
        self, db_session, product_service
    ):
        business_id = uuid.uuid4()
        product = await product_service.create_product(
            business_id=business_id, sku="BEV-4", name="Cola", unit_price=Decimal("2.00")
        )

        other_business_id = uuid.uuid4()
        category = Category(business_id=other_business_id, name="Not Yours")
        cat_repo = CategoryRepository(db_session)
        created_category = await cat_repo.create(category)
        await cat_repo.commit()

        with pytest.raises(InvalidProductReferenceError):
            await product_service.update_product(
                business_id=business_id,
                product_id=product.id,
                category_id=created_category.id,
            )
