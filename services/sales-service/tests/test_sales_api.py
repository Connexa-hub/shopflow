import uuid
from decimal import Decimal

from shopflow_constants import Role

from tests.conftest import make_access_token


class TestHealthEndpoint:
    async def test_health_check(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "service": "sales-service"}


class TestCreateSaleEndpoint:
    async def test_cashier_can_create_a_sale(self, client, fake_inventory, cashier_headers):
        location_id = uuid.uuid4()
        product = fake_inventory.add_product(unit_price=Decimal("20.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("10"))

        resp = await client.post(
            "/api/v1/sales",
            headers=cashier_headers,
            json={
                "location_id": str(location_id),
                "items": [{"product_id": str(product.id), "quantity": "2"}],
                "payments": [{"method": "cash", "amount": "40.00"}],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "completed"
        assert body["total"] == "40.00"
        assert body["receipt_number"] == "RCP-000001"
        assert len(body["items"]) == 1
        assert body["items"][0]["sku"] == product.sku

    async def test_insufficient_stock_returns_409(self, client, fake_inventory, cashier_headers):
        location_id = uuid.uuid4()
        product = fake_inventory.add_product(unit_price=Decimal("10.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("1"))

        resp = await client.post(
            "/api/v1/sales",
            headers=cashier_headers,
            json={
                "location_id": str(location_id),
                "items": [{"product_id": str(product.id), "quantity": "5"}],
                "payments": [{"method": "cash", "amount": "50.00"}],
            },
        )
        assert resp.status_code == 409

    async def test_unknown_product_returns_400(self, client, cashier_headers):
        resp = await client.post(
            "/api/v1/sales",
            headers=cashier_headers,
            json={
                "location_id": str(uuid.uuid4()),
                "items": [{"product_id": str(uuid.uuid4()), "quantity": "1"}],
                "payments": [{"method": "cash", "amount": "10.00"}],
            },
        )
        assert resp.status_code == 400

    async def test_duplicate_product_in_request_rejected_at_schema_level(
        self, client, fake_inventory, cashier_headers
    ):
        product = fake_inventory.add_product(unit_price=Decimal("10.00"))
        resp = await client.post(
            "/api/v1/sales",
            headers=cashier_headers,
            json={
                "location_id": str(uuid.uuid4()),
                "items": [
                    {"product_id": str(product.id), "quantity": "1"},
                    {"product_id": str(product.id), "quantity": "2"},
                ],
                "payments": [{"method": "cash", "amount": "30.00"}],
            },
        )
        assert resp.status_code == 422  # caught by CreateSaleRequest's model_validator

    async def test_missing_token_returns_401(self, client):
        resp = await client.post(
            "/api/v1/sales",
            json={
                "location_id": str(uuid.uuid4()),
                "items": [{"product_id": str(uuid.uuid4()), "quantity": "1"}],
                "payments": [{"method": "cash", "amount": "10.00"}],
            },
        )
        assert resp.status_code == 401

    async def test_staff_role_cannot_create_sale(self, client, business_id):
        # STAFF has INVENTORY_READ but not SALES_CREATE per DEFAULT_ROLE_PERMISSIONS.
        token = make_access_token(business_id=business_id, role=Role.STAFF)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.post(
            "/api/v1/sales",
            headers=headers,
            json={
                "location_id": str(uuid.uuid4()),
                "items": [{"product_id": str(uuid.uuid4()), "quantity": "1"}],
                "payments": [{"method": "cash", "amount": "10.00"}],
            },
        )
        assert resp.status_code == 403

    async def test_zero_quantity_rejected_at_schema_level(self, client, cashier_headers):
        resp = await client.post(
            "/api/v1/sales",
            headers=cashier_headers,
            json={
                "location_id": str(uuid.uuid4()),
                "items": [{"product_id": str(uuid.uuid4()), "quantity": "0"}],
                "payments": [{"method": "cash", "amount": "10.00"}],
            },
        )
        assert resp.status_code == 422

    async def test_credit_sale_accepted_and_balance_due_reported(
        self, client, fake_inventory, cashier_headers
    ):
        location_id = uuid.uuid4()
        product = fake_inventory.add_product(unit_price=Decimal("50.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("5"))

        resp = await client.post(
            "/api/v1/sales",
            headers=cashier_headers,
            json={
                "location_id": str(location_id),
                "customer_id": str(uuid.uuid4()),
                "items": [{"product_id": str(product.id), "quantity": "1"}],
                "payments": [
                    {"method": "cash", "amount": "20.00"},
                    {"method": "credit", "amount": "30.00"},
                ],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["amount_paid"] == "20.00"
        assert body["balance_due"] == "30.00"


class TestGetAndListSales:
    async def test_get_sale_returns_full_detail(self, client, fake_inventory, cashier_headers):
        location_id = uuid.uuid4()
        product = fake_inventory.add_product(unit_price=Decimal("15.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("10"))

        create_resp = await client.post(
            "/api/v1/sales",
            headers=cashier_headers,
            json={
                "location_id": str(location_id),
                "items": [{"product_id": str(product.id), "quantity": "1"}],
                "payments": [{"method": "cash", "amount": "15.00"}],
            },
        )
        sale_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/sales/{sale_id}", headers=cashier_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == sale_id
        assert len(resp.json()["payments"]) == 1

    async def test_get_nonexistent_sale_returns_404(self, client, cashier_headers):
        resp = await client.get(f"/api/v1/sales/{uuid.uuid4()}", headers=cashier_headers)
        assert resp.status_code == 404

    async def test_list_sales_returns_created_sales(self, client, fake_inventory, cashier_headers):
        location_id = uuid.uuid4()
        product = fake_inventory.add_product(unit_price=Decimal("5.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("20"))

        for _ in range(2):
            await client.post(
                "/api/v1/sales",
                headers=cashier_headers,
                json={
                    "location_id": str(location_id),
                    "items": [{"product_id": str(product.id), "quantity": "1"}],
                    "payments": [{"method": "cash", "amount": "5.00"}],
                },
            )

        resp = await client.get("/api/v1/sales", headers=cashier_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestVoidSaleEndpoint:
    async def test_cashier_cannot_void_a_sale(self, client, fake_inventory, cashier_headers):
        location_id = uuid.uuid4()
        product = fake_inventory.add_product(unit_price=Decimal("10.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("10"))

        create_resp = await client.post(
            "/api/v1/sales",
            headers=cashier_headers,
            json={
                "location_id": str(location_id),
                "items": [{"product_id": str(product.id), "quantity": "1"}],
                "payments": [{"method": "cash", "amount": "10.00"}],
            },
        )
        sale_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/sales/{sale_id}/void",
            headers=cashier_headers,
            json={"reason": "Trying to void my own sale"},
        )
        assert resp.status_code == 403

    async def test_manager_can_void_a_sale_and_stock_is_restored(
        self, client, fake_inventory, cashier_headers, manager_headers
    ):
        location_id = uuid.uuid4()
        product = fake_inventory.add_product(unit_price=Decimal("10.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("10"))

        create_resp = await client.post(
            "/api/v1/sales",
            headers=cashier_headers,
            json={
                "location_id": str(location_id),
                "items": [{"product_id": str(product.id), "quantity": "3"}],
                "payments": [{"method": "cash", "amount": "30.00"}],
            },
        )
        sale_id = create_resp.json()["id"]
        assert fake_inventory.stock_levels[(product.id, location_id)] == Decimal("7")

        resp = await client.post(
            f"/api/v1/sales/{sale_id}/void",
            headers=manager_headers,
            json={"reason": "Customer changed their mind"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "voided"
        assert fake_inventory.stock_levels[(product.id, location_id)] == Decimal("10")

    async def test_void_with_empty_reason_returns_422(
        self, client, fake_inventory, cashier_headers, manager_headers
    ):
        location_id = uuid.uuid4()
        product = fake_inventory.add_product(unit_price=Decimal("10.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("10"))
        create_resp = await client.post(
            "/api/v1/sales",
            headers=cashier_headers,
            json={
                "location_id": str(location_id),
                "items": [{"product_id": str(product.id), "quantity": "1"}],
                "payments": [{"method": "cash", "amount": "10.00"}],
            },
        )
        sale_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/sales/{sale_id}/void", headers=manager_headers, json={"reason": ""}
        )
        assert resp.status_code == 422  # caught by VoidSaleRequest's min_length=1


class TestCrossTenantIsolation:
    async def test_cannot_read_another_businesss_sale(
        self, client, fake_inventory, cashier_headers
    ):
        location_id = uuid.uuid4()
        product = fake_inventory.add_product(unit_price=Decimal("10.00"))
        fake_inventory.set_stock(product_id=product.id, location_id=location_id, quantity=Decimal("10"))

        create_resp = await client.post(
            "/api/v1/sales",
            headers=cashier_headers,
            json={
                "location_id": str(location_id),
                "items": [{"product_id": str(product.id), "quantity": "1"}],
                "payments": [{"method": "cash", "amount": "10.00"}],
            },
        )
        sale_id = create_resp.json()["id"]

        other_token = make_access_token(business_id=uuid.uuid4(), role=Role.BUSINESS_OWNER)
        other_headers = {"Authorization": f"Bearer {other_token}"}

        resp = await client.get(f"/api/v1/sales/{sale_id}", headers=other_headers)
        assert resp.status_code == 404
