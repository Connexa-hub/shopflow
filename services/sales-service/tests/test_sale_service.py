import uuid
from decimal import Decimal

import pytest

from app.core.inventory_client import (
    InsufficientStockUpstreamError,
    InventoryServiceUnavailableError,
)
from app.domain.models import PaymentMethod, SaleStatus
from app.repositories.sale_repository import SaleRepository
from app.services.sale_service import (
    SaleAlreadyVoidedError,
    SaleItemInput,
    SaleNotFoundError,
    SalePaymentInput,
    SaleService,
    SaleValidationError,
)


@pytest.fixture
def sale_service(db_session, fake_inventory) -> SaleService:
    return SaleService(SaleRepository(db_session), fake_inventory)


@pytest.fixture
def location_id() -> uuid.UUID:
    return uuid.uuid4()


class TestCreateSaleHappyPath:
    async def test_single_item_cash_sale(self, sale_service, fake_inventory, business_id, location_id):
        product = fake_inventory.add_product(unit_price=Decimal("15.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("50"))

        sale = await sale_service.create_sale(
            business_id=business_id,
            location_id=location_id,
            cashier_id=uuid.uuid4(),
            bearer_token="fake-token",
            items=[SaleItemInput(product_id=product.id, quantity=Decimal("3"))],
            payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("45.00"))],
        )

        assert sale.status == SaleStatus.COMPLETED.value
        assert sale.subtotal == Decimal("45.00")
        assert sale.total == Decimal("45.00")
        assert sale.amount_paid == Decimal("45.00")
        assert sale.balance_due == Decimal("0")
        assert sale.receipt_number == "RCP-000001"

    async def test_receipt_numbers_increment_sequentially_per_business(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        product = fake_inventory.add_product(unit_price=Decimal("1.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("100"))

        for _ in range(3):
            sale = await sale_service.create_sale(
                business_id=business_id,
                location_id=location_id,
                cashier_id=uuid.uuid4(),
                bearer_token="fake-token",
                items=[SaleItemInput(product_id=product.id, quantity=Decimal("1"))],
                payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("1.00"))],
            )
        assert sale.receipt_number == "RCP-000003"

    async def test_multi_item_sale_computes_correct_subtotal(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        a = fake_inventory.add_product(sku="A", unit_price=Decimal("10.00"))
        b = fake_inventory.add_product(sku="B", unit_price=Decimal("5.00"))
        fake_inventory.set_stock(product_id=a.id, location_id=location_id, quantity=Decimal("10"))
        fake_inventory.set_stock(product_id=b.id, location_id=location_id, quantity=Decimal("10"))

        sale = await sale_service.create_sale(
            business_id=business_id,
            location_id=location_id,
            cashier_id=uuid.uuid4(),
            bearer_token="fake-token",
            items=[
                SaleItemInput(product_id=a.id, quantity=Decimal("2")),  # 20.00
                SaleItemInput(product_id=b.id, quantity=Decimal("3")),  # 15.00
            ],
            payments=[SalePaymentInput(method=PaymentMethod.CARD, amount=Decimal("35.00"))],
        )
        assert sale.subtotal == Decimal("35.00")
        assert sale.total == Decimal("35.00")

    async def test_split_payment_across_methods(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        product = fake_inventory.add_product(unit_price=Decimal("100.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("5"))

        sale = await sale_service.create_sale(
            business_id=business_id,
            location_id=location_id,
            cashier_id=uuid.uuid4(),
            bearer_token="fake-token",
            items=[SaleItemInput(product_id=product.id, quantity=Decimal("1"))],
            payments=[
                SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("60.00")),
                SalePaymentInput(method=PaymentMethod.CARD, amount=Decimal("40.00")),
            ],
        )
        assert sale.amount_paid == Decimal("100.00")
        assert sale.balance_due == Decimal("0")

    async def test_credit_sale_leaves_balance_due(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        product = fake_inventory.add_product(unit_price=Decimal("50.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("5"))

        sale = await sale_service.create_sale(
            business_id=business_id,
            location_id=location_id,
            cashier_id=uuid.uuid4(),
            bearer_token="fake-token",
            items=[SaleItemInput(product_id=product.id, quantity=Decimal("1"))],
            payments=[
                SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("20.00")),
                SalePaymentInput(method=PaymentMethod.CREDIT, amount=Decimal("30.00")),
            ],
        )
        assert sale.amount_paid == Decimal("20.00")
        assert sale.balance_due == Decimal("30.00")

    async def test_line_item_discount_reduces_total(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        product = fake_inventory.add_product(unit_price=Decimal("20.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("5"))

        sale = await sale_service.create_sale(
            business_id=business_id,
            location_id=location_id,
            cashier_id=uuid.uuid4(),
            bearer_token="fake-token",
            items=[
                SaleItemInput(product_id=product.id, quantity=Decimal("1"), discount_amount=Decimal("5.00"))
            ],
            payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("15.00"))],
        )
        assert sale.subtotal == Decimal("20.00")
        assert sale.discount_total == Decimal("5.00")
        assert sale.total == Decimal("15.00")

    async def test_stock_is_actually_deducted(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        product = fake_inventory.add_product(unit_price=Decimal("10.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("10"))

        await sale_service.create_sale(
            business_id=business_id,
            location_id=location_id,
            cashier_id=uuid.uuid4(),
            bearer_token="fake-token",
            items=[SaleItemInput(product_id=product.id, quantity=Decimal("4"))],
            payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("40.00"))],
        )
        assert fake_inventory.stock_levels[(product.id, location_id)] == Decimal("6")


class TestCreateSaleValidation:
    async def test_rejects_empty_items(self, sale_service, business_id, location_id):
        with pytest.raises(SaleValidationError):
            await sale_service.create_sale(
                business_id=business_id,
                location_id=location_id,
                cashier_id=uuid.uuid4(),
                bearer_token="fake-token",
                items=[],
                payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("1"))],
            )

    async def test_rejects_empty_payments(self, sale_service, fake_inventory, business_id, location_id):
        product = fake_inventory.add_product()
        with pytest.raises(SaleValidationError):
            await sale_service.create_sale(
                business_id=business_id,
                location_id=location_id,
                cashier_id=uuid.uuid4(),
                bearer_token="fake-token",
                items=[SaleItemInput(product_id=product.id, quantity=Decimal("1"))],
                payments=[],
            )

    async def test_rejects_unknown_product(self, sale_service, business_id, location_id):
        with pytest.raises(SaleValidationError):
            await sale_service.create_sale(
                business_id=business_id,
                location_id=location_id,
                cashier_id=uuid.uuid4(),
                bearer_token="fake-token",
                items=[SaleItemInput(product_id=uuid.uuid4(), quantity=Decimal("1"))],
                payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("1"))],
            )

    async def test_rejects_inactive_product(self, sale_service, fake_inventory, business_id, location_id):
        product = fake_inventory.add_product(unit_price=Decimal("10"), is_active=False)
        with pytest.raises(SaleValidationError):
            await sale_service.create_sale(
                business_id=business_id,
                location_id=location_id,
                cashier_id=uuid.uuid4(),
                bearer_token="fake-token",
                items=[SaleItemInput(product_id=product.id, quantity=Decimal("1"))],
                payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("10"))],
            )

    async def test_rejects_payments_not_covering_total_without_credit(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        product = fake_inventory.add_product(unit_price=Decimal("100"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("5"))
        with pytest.raises(SaleValidationError):
            await sale_service.create_sale(
                business_id=business_id,
                location_id=location_id,
                cashier_id=uuid.uuid4(),
                bearer_token="fake-token",
                items=[SaleItemInput(product_id=product.id, quantity=Decimal("1"))],
                payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("50"))],
            )

    async def test_rejects_overpayment(self, sale_service, fake_inventory, business_id, location_id):
        product = fake_inventory.add_product(unit_price=Decimal("10"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("5"))
        with pytest.raises(SaleValidationError):
            await sale_service.create_sale(
                business_id=business_id,
                location_id=location_id,
                cashier_id=uuid.uuid4(),
                bearer_token="fake-token",
                items=[SaleItemInput(product_id=product.id, quantity=Decimal("1"))],
                payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("20"))],
            )

    async def test_rejects_duplicate_product_in_one_sale(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        product = fake_inventory.add_product(unit_price=Decimal("10"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("5"))
        with pytest.raises(SaleValidationError):
            await sale_service.create_sale(
                business_id=business_id,
                location_id=location_id,
                cashier_id=uuid.uuid4(),
                bearer_token="fake-token",
                items=[
                    SaleItemInput(product_id=product.id, quantity=Decimal("1")),
                    SaleItemInput(product_id=product.id, quantity=Decimal("1")),
                ],
                payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("20"))],
            )


class TestCreateSaleInventoryFailures:
    """These verify sales-service correctly propagates and translates
    inventory-service failures — the core value of the cross-service
    integration being correct, not just the happy path."""

    async def test_insufficient_stock_propagates_and_nothing_is_persisted(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        product = fake_inventory.add_product(unit_price=Decimal("10"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("1"))

        with pytest.raises(InsufficientStockUpstreamError):
            await sale_service.create_sale(
                business_id=business_id,
                location_id=location_id,
                cashier_id=uuid.uuid4(),
                bearer_token="fake-token",
                items=[SaleItemInput(product_id=product.id, quantity=Decimal("5"))],
                payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("50"))],
            )
        # Nothing should have been recorded — the sale never happened.
        sales = await sale_service.list_sales(business_id=business_id)
        assert sales == []

    async def test_inventory_service_unavailable_propagates(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        product = fake_inventory.add_product(unit_price=Decimal("10"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("10"))
        fake_inventory.fail_batch_sale_with = InventoryServiceUnavailableError("down for maintenance")

        with pytest.raises(InventoryServiceUnavailableError):
            await sale_service.create_sale(
                business_id=business_id,
                location_id=location_id,
                cashier_id=uuid.uuid4(),
                bearer_token="fake-token",
                items=[SaleItemInput(product_id=product.id, quantity=Decimal("1"))],
                payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("10"))],
            )


class TestVoidSale:
    async def test_void_restores_stock_and_marks_voided(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        product = fake_inventory.add_product(unit_price=Decimal("10"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("10"))

        sale = await sale_service.create_sale(
            business_id=business_id,
            location_id=location_id,
            cashier_id=uuid.uuid4(),
            bearer_token="fake-token",
            items=[SaleItemInput(product_id=product.id, quantity=Decimal("3"))],
            payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("30"))],
        )
        assert fake_inventory.stock_levels[(product.id, location_id)] == Decimal("7")

        voided = await sale_service.void_sale(
            business_id=business_id,
            sale_id=sale.id,
            bearer_token="fake-token",
            reason="Customer returned items",
        )
        assert voided.status == SaleStatus.VOIDED.value
        assert voided.void_reason == "Customer returned items"
        assert voided.voided_at is not None
        assert fake_inventory.stock_levels[(product.id, location_id)] == Decimal("10")

    async def test_cannot_void_already_voided_sale(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        product = fake_inventory.add_product(unit_price=Decimal("10"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("10"))
        sale = await sale_service.create_sale(
            business_id=business_id,
            location_id=location_id,
            cashier_id=uuid.uuid4(),
            bearer_token="fake-token",
            items=[SaleItemInput(product_id=product.id, quantity=Decimal("1"))],
            payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("10"))],
        )
        await sale_service.void_sale(
            business_id=business_id, sale_id=sale.id, bearer_token="fake-token", reason="First void"
        )
        with pytest.raises(SaleAlreadyVoidedError):
            await sale_service.void_sale(
                business_id=business_id, sale_id=sale.id, bearer_token="fake-token", reason="Second void"
            )

    async def test_void_requires_a_reason(self, sale_service, business_id):
        with pytest.raises(SaleValidationError):
            await sale_service.void_sale(
                business_id=business_id, sale_id=uuid.uuid4(), bearer_token="fake-token", reason=""
            )

    async def test_void_nonexistent_sale_raises_not_found(self, sale_service, business_id):
        with pytest.raises(SaleNotFoundError):
            await sale_service.void_sale(
                business_id=business_id,
                sale_id=uuid.uuid4(),
                bearer_token="fake-token",
                reason="Doesn't exist",
            )


class TestTenantIsolation:
    async def test_cannot_get_another_businesss_sale(
        self, sale_service, fake_inventory, business_id, location_id
    ):
        product = fake_inventory.add_product(unit_price=Decimal("10"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("10"))
        sale = await sale_service.create_sale(
            business_id=business_id,
            location_id=location_id,
            cashier_id=uuid.uuid4(),
            bearer_token="fake-token",
            items=[SaleItemInput(product_id=product.id, quantity=Decimal("1"))],
            payments=[SalePaymentInput(method=PaymentMethod.CASH, amount=Decimal("10"))],
        )
        with pytest.raises(SaleNotFoundError):
            await sale_service.get_sale(business_id=uuid.uuid4(), sale_id=sale.id)
