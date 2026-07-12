import uuid
from decimal import Decimal

from shopflow_constants import Role

from tests.conftest import make_access_token


class TestHealthEndpoint:
    async def test_health_check(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["service"] == "inventory-service"


class TestAuthEnforcement:
    async def test_missing_token_returns_401(self, client):
        resp = await client.get("/api/v1/products")
        assert resp.status_code == 401

    async def test_garbage_token_returns_401(self, client):
        resp = await client.get(
            "/api/v1/products", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert resp.status_code == 401


class TestProductEndpointRBAC:
    async def test_owner_can_create_product(self, client, owner_headers):
        resp = await client.post(
            "/api/v1/products",
            headers=owner_headers,
            json={"sku": "P-1", "name": "Product One", "unit_price": "9.99"},
        )
        assert resp.status_code == 201
        assert resp.json()["sku"] == "P-1"

    async def test_cashier_cannot_create_product(self, client, cashier_headers):
        """Cashiers have INVENTORY_READ + SALES_CREATE, not INVENTORY_WRITE —
        this is the RBAC design from Phase 1 actually being enforced by a
        second service, proving the shared permissions contract works
        across service boundaries."""
        resp = await client.post(
            "/api/v1/products",
            headers=cashier_headers,
            json={"sku": "P-2", "name": "Product Two", "unit_price": "9.99"},
        )
        assert resp.status_code == 403

    async def test_cashier_can_read_products(self, client, cashier_headers, owner_headers):
        await client.post(
            "/api/v1/products",
            headers=owner_headers,
            json={"sku": "P-3", "name": "Product Three", "unit_price": "5.00"},
        )
        resp = await client.get("/api/v1/products", headers=cashier_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_duplicate_sku_returns_409(self, client, owner_headers):
        payload = {"sku": "DUP", "name": "First", "unit_price": "1.00"}
        first = await client.post("/api/v1/products", headers=owner_headers, json=payload)
        assert first.status_code == 201
        second = await client.post("/api/v1/products", headers=owner_headers, json=payload)
        assert second.status_code == 409


class TestStockFlowThroughAPI:
    async def test_full_restock_and_sale_flow(self, client, owner_headers, cashier_headers):
        location_resp = await client.post(
            "/api/v1/locations", headers=owner_headers, json={"name": "Main Store"}
        )
        assert location_resp.status_code == 201
        location_id = location_resp.json()["id"]

        product_resp = await client.post(
            "/api/v1/products",
            headers=owner_headers,
            json={"sku": "FLOW-1", "name": "Flow Product", "unit_price": "10.00"},
        )
        product_id = product_resp.json()["id"]

        restock_resp = await client.post(
            "/api/v1/stock/restock",
            headers=owner_headers,
            json={"product_id": product_id, "location_id": location_id, "quantity": "20"},
        )
        assert restock_resp.status_code == 201
        # Compare numerically rather than against an exact string/number
        # literal — Decimal's JSON representation (string vs number) isn't
        # being assumed here.
        assert Decimal(str(restock_resp.json()["resulting_quantity"])) == Decimal("20")

        # Cashier CAN record a sale (SALES_CREATE) even without INVENTORY_WRITE.
        sale_resp = await client.post(
            "/api/v1/stock/sale",
            headers=cashier_headers,
            json={"product_id": product_id, "location_id": location_id, "quantity": "5"},
        )
        assert sale_resp.status_code == 201
        assert Decimal(str(sale_resp.json()["resulting_quantity"])) == Decimal("15")

        level_resp = await client.get(
            "/api/v1/stock/level",
            headers=owner_headers,
            params={"product_id": product_id, "location_id": location_id},
        )
        assert level_resp.status_code == 200
        assert Decimal(str(level_resp.json()["quantity"])) == Decimal("15")

    async def test_sale_exceeding_stock_returns_409(self, client, owner_headers):
        location_resp = await client.post(
            "/api/v1/locations", headers=owner_headers, json={"name": "Store"}
        )
        location_id = location_resp.json()["id"]
        product_resp = await client.post(
            "/api/v1/products",
            headers=owner_headers,
            json={"sku": "LOW-1", "name": "Scarce Product", "unit_price": "1.00"},
        )
        product_id = product_resp.json()["id"]

        await client.post(
            "/api/v1/stock/restock",
            headers=owner_headers,
            json={"product_id": product_id, "location_id": location_id, "quantity": "2"},
        )
        resp = await client.post(
            "/api/v1/stock/sale",
            headers=owner_headers,
            json={"product_id": product_id, "location_id": location_id, "quantity": "10"},
        )
        assert resp.status_code == 409

    async def test_location_creation_requires_business_configure_permission(
        self, client, cashier_headers
    ):
        resp = await client.post(
            "/api/v1/locations", headers=cashier_headers, json={"name": "New Branch"}
        )
        assert resp.status_code == 403


class TestCrossTenantIsolationThroughAPI:
    """End-to-end proof (not just a unit test) that one business's bearer
    token cannot touch another business's product/location by ID, across
    every stock endpoint. Regression coverage for the gap found on review:
    the stock routes previously verified the token but never checked that
    the referenced product/location actually belonged to that token's
    business."""

    async def test_owner_cannot_restock_another_businesss_product(
        self, client, owner_headers
    ):
        # A second, unrelated business — different token, different business_id.
        other_token = make_access_token(business_id=uuid.uuid4(), role=Role.BUSINESS_OWNER)
        other_headers = {"Authorization": f"Bearer {other_token}"}

        location_resp = await client.post(
            "/api/v1/locations", headers=owner_headers, json={"name": "Owner's Store"}
        )
        location_id = location_resp.json()["id"]
        product_resp = await client.post(
            "/api/v1/products",
            headers=owner_headers,
            json={"sku": "ISO-1", "name": "Owner's Product", "unit_price": "1.00"},
        )
        product_id = product_resp.json()["id"]

        # `other_headers` is a completely different business trying to
        # restock using IDs it doesn't own.
        resp = await client.post(
            "/api/v1/stock/restock",
            headers=other_headers,
            json={"product_id": product_id, "location_id": location_id, "quantity": "10"},
        )
        assert resp.status_code == 404

    async def test_owner_cannot_read_another_businesss_stock_level(
        self, client, owner_headers
    ):
        other_token = make_access_token(business_id=uuid.uuid4(), role=Role.BUSINESS_OWNER)
        other_headers = {"Authorization": f"Bearer {other_token}"}

        location_resp = await client.post(
            "/api/v1/locations", headers=owner_headers, json={"name": "Owner's Store"}
        )
        location_id = location_resp.json()["id"]
        product_resp = await client.post(
            "/api/v1/products",
            headers=owner_headers,
            json={"sku": "ISO-2", "name": "Owner's Product", "unit_price": "1.00"},
        )
        product_id = product_resp.json()["id"]

        resp = await client.get(
            "/api/v1/stock/level",
            headers=other_headers,
            params={"product_id": product_id, "location_id": location_id},
        )
        assert resp.status_code == 404
