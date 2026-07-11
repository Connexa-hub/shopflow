class TestHealthEndpoint:
    async def test_health_check(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "service": "auth-service"}


class TestRegistrationEndpoint:
    async def test_register_business_owner_success(self, client):
        resp = await client.post(
            "/api/v1/auth/register/business-owner",
            json={
                "business_name": "Kemi's Pharmacy",
                "full_name": "Kemi Ola",
                "email": "kemi@example.com",
                "password": "Str0ngPass",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == "kemi@example.com"
        assert body["role"] == "business_owner"
        assert body["business_id"] is not None

    async def test_register_rejects_weak_password(self, client):
        resp = await client.post(
            "/api/v1/auth/register/business-owner",
            json={
                "business_name": "Store",
                "full_name": "Owner",
                "email": "weak@example.com",
                "password": "alllowercase",  # no digit
            },
        )
        assert resp.status_code == 422

    async def test_register_duplicate_email_returns_409(self, client):
        payload = {
            "business_name": "Store",
            "full_name": "Owner",
            "email": "twice@example.com",
            "password": "Str0ngPass",
        }
        first = await client.post("/api/v1/auth/register/business-owner", json=payload)
        assert first.status_code == 201
        second = await client.post("/api/v1/auth/register/business-owner", json=payload)
        assert second.status_code == 409


class TestLoginEndpoint:
    async def test_login_success_returns_token_pair(self, client):
        await client.post(
            "/api/v1/auth/register/business-owner",
            json={
                "business_name": "Store",
                "full_name": "Owner",
                "email": "login@example.com",
                "password": "Str0ngPass",
            },
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "Str0ngPass"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"

    async def test_login_wrong_password_returns_401(self, client):
        await client.post(
            "/api/v1/auth/register/business-owner",
            json={
                "business_name": "Store",
                "full_name": "Owner",
                "email": "login2@example.com",
                "password": "Str0ngPass",
            },
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "login2@example.com", "password": "WrongOne1"},
        )
        assert resp.status_code == 401


class TestRefreshEndpoint:
    async def test_refresh_success(self, client):
        await client.post(
            "/api/v1/auth/register/business-owner",
            json={
                "business_name": "Store",
                "full_name": "Owner",
                "email": "refresh@example.com",
                "password": "Str0ngPass",
            },
        )
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "refresh@example.com", "password": "Str0ngPass"},
        )
        refresh_token = login_resp.json()["refresh_token"]

        resp = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_refresh_invalid_token_returns_401(self, client):
        resp = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": "garbage"}
        )
        assert resp.status_code == 401
