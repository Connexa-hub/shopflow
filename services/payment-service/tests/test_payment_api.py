import json
import uuid

from shopflow_constants import Role

from tests.conftest import make_access_token


class TestHealthEndpoint:
    async def test_health_check(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "service": "payment-service"}


class TestInitializePaymentEndpoint:
    async def test_cashier_can_initialize_payment(self, client, cashier_headers):
        resp = await client.post(
            "/api/v1/payments",
            headers=cashier_headers,
            json={
                "provider": "paystack",
                "amount": "2500.00",
                "currency": "NGN",
                "customer_email": "buyer@example.com",
                "purpose": "sale_payment",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"
        assert body["checkout_url"] is not None

    async def test_staff_cannot_initialize_payment(self, client, business_id):
        # STAFF only has INVENTORY_READ per DEFAULT_ROLE_PERMISSIONS.
        token = make_access_token(business_id=business_id, role=Role.STAFF)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.post(
            "/api/v1/payments",
            headers=headers,
            json={
                "provider": "paystack",
                "amount": "100",
                "currency": "NGN",
                "customer_email": "buyer@example.com",
                "purpose": "sale_payment",
            },
        )
        assert resp.status_code == 403

    async def test_missing_token_returns_401(self, client):
        resp = await client.post(
            "/api/v1/payments",
            json={
                "provider": "paystack",
                "amount": "100",
                "currency": "NGN",
                "customer_email": "buyer@example.com",
                "purpose": "sale_payment",
            },
        )
        assert resp.status_code == 401

    async def test_unconfigured_provider_returns_400(self, client, cashier_headers):
        # Only paystack is registered via the fake_paystack fixture override.
        resp = await client.post(
            "/api/v1/payments",
            headers=cashier_headers,
            json={
                "provider": "monnify",
                "amount": "100",
                "currency": "NGN",
                "customer_email": "buyer@example.com",
                "purpose": "sale_payment",
            },
        )
        assert resp.status_code == 400

    async def test_invalid_email_rejected_at_schema_level(self, client, cashier_headers):
        resp = await client.post(
            "/api/v1/payments",
            headers=cashier_headers,
            json={
                "provider": "paystack",
                "amount": "100",
                "currency": "NGN",
                "customer_email": "not-an-email",
                "purpose": "sale_payment",
            },
        )
        assert resp.status_code == 422

    async def test_negative_amount_rejected_at_schema_level(self, client, cashier_headers):
        resp = await client.post(
            "/api/v1/payments",
            headers=cashier_headers,
            json={
                "provider": "paystack",
                "amount": "-5",
                "currency": "NGN",
                "customer_email": "buyer@example.com",
                "purpose": "sale_payment",
            },
        )
        assert resp.status_code == 422


class TestGetAndListPayments:
    async def test_get_payment(self, client, cashier_headers):
        created = await client.post(
            "/api/v1/payments",
            headers=cashier_headers,
            json={
                "provider": "paystack",
                "amount": "100",
                "currency": "NGN",
                "customer_email": "buyer@example.com",
                "purpose": "sale_payment",
            },
        )
        transaction_id = created.json()["id"]
        resp = await client.get(f"/api/v1/payments/{transaction_id}", headers=cashier_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == transaction_id

    async def test_get_nonexistent_payment_returns_404(self, client, cashier_headers):
        resp = await client.get(f"/api/v1/payments/{uuid.uuid4()}", headers=cashier_headers)
        assert resp.status_code == 404

    async def test_list_payments(self, client, cashier_headers):
        await client.post(
            "/api/v1/payments",
            headers=cashier_headers,
            json={
                "provider": "paystack",
                "amount": "100",
                "currency": "NGN",
                "customer_email": "buyer@example.com",
                "purpose": "sale_payment",
            },
        )
        resp = await client.get("/api/v1/payments", headers=cashier_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestCrossTenantIsolation:
    async def test_cannot_read_another_businesss_payment(self, client, cashier_headers):
        created = await client.post(
            "/api/v1/payments",
            headers=cashier_headers,
            json={
                "provider": "paystack",
                "amount": "100",
                "currency": "NGN",
                "customer_email": "buyer@example.com",
                "purpose": "sale_payment",
            },
        )
        transaction_id = created.json()["id"]

        other_token = make_access_token(business_id=uuid.uuid4(), role=Role.BUSINESS_OWNER)
        other_headers = {"Authorization": f"Bearer {other_token}"}
        resp = await client.get(f"/api/v1/payments/{transaction_id}", headers=other_headers)
        assert resp.status_code == 404


class TestWebhookEndpoint:
    async def test_webhook_no_auth_required(self, client, fake_paystack):
        """Webhooks are called by the provider directly — no bearer token
        at all, unlike every other route in this service."""
        fake_paystack.next_webhook_signature_valid = True
        resp = await client.post(
            "/api/v1/webhooks/paystack",
            content=json.dumps({"event": "charge.success", "data": {}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200

    async def test_webhook_invalid_signature_returns_401(self, client, fake_paystack):
        fake_paystack.next_webhook_signature_valid = False
        resp = await client.post(
            "/api/v1/webhooks/paystack",
            content=json.dumps({"event": "charge.success", "data": {}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    async def test_webhook_unconfigured_provider_returns_400(self, client):
        # Only paystack is registered in this test's fixture override.
        resp = await client.post(
            "/api/v1/webhooks/flutterwave",
            content=json.dumps({"event": "charge.success"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
