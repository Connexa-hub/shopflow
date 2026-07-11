import pytest

from app.services.auth_service import (
    AccountLockedError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidTokenError,
)


class TestRegisterBusinessOwner:
    async def test_registers_new_business_owner(self, auth_service):
        user = await auth_service.register_business_owner(
            business_name="Mama Ngozi Provisions",
            full_name="Ngozi Adeyemi",
            email="ngozi@example.com",
            password="Str0ngPass",
        )
        assert user.email == "ngozi@example.com"
        assert user.role == "business_owner"
        assert user.business_id is not None
        assert user.business.name == "Mama Ngozi Provisions"
        assert user.business.slug == "mama-ngozi-provisions"

    async def test_rejects_duplicate_email(self, auth_service):
        await auth_service.register_business_owner(
            business_name="Store A",
            full_name="Owner A",
            email="dup@example.com",
            password="Str0ngPass",
        )
        with pytest.raises(EmailAlreadyRegisteredError):
            await auth_service.register_business_owner(
                business_name="Store B",
                full_name="Owner B",
                email="dup@example.com",
                password="Str0ngPass",
            )


class TestAuthenticate:
    async def test_authenticates_with_correct_password(self, auth_service):
        await auth_service.register_business_owner(
            business_name="Store",
            full_name="Owner",
            email="owner@example.com",
            password="Str0ngPass",
        )
        user = await auth_service.authenticate(email="owner@example.com", password="Str0ngPass")
        assert user.email == "owner@example.com"

    async def test_rejects_wrong_password(self, auth_service):
        await auth_service.register_business_owner(
            business_name="Store",
            full_name="Owner",
            email="owner2@example.com",
            password="Str0ngPass",
        )
        with pytest.raises(InvalidCredentialsError):
            await auth_service.authenticate(email="owner2@example.com", password="WrongPass1")

    async def test_rejects_unknown_email(self, auth_service):
        with pytest.raises(InvalidCredentialsError):
            await auth_service.authenticate(email="nobody@example.com", password="whatever1")

    async def test_locks_account_after_max_failed_attempts(self, auth_service):
        await auth_service.register_business_owner(
            business_name="Store",
            full_name="Owner",
            email="lockme@example.com",
            password="Str0ngPass",
        )
        for _ in range(auth_service._settings.max_failed_login_attempts):
            with pytest.raises(InvalidCredentialsError):
                await auth_service.authenticate(email="lockme@example.com", password="wrong1234")

        with pytest.raises(AccountLockedError):
            await auth_service.authenticate(email="lockme@example.com", password="Str0ngPass")


class TestTokenLifecycle:
    async def test_issues_token_pair_with_role_permissions(self, auth_service):
        user = await auth_service.register_business_owner(
            business_name="Store",
            full_name="Owner",
            email="tokens@example.com",
            password="Str0ngPass",
        )
        access_token, refresh_token = await auth_service.issue_token_pair(user)
        assert access_token
        assert refresh_token

        from app.core.security import decode_token

        payload = decode_token(access_token)
        assert payload["role"] == "business_owner"
        assert "business:configure" in payload["permissions"]

    async def test_refresh_rotates_token_and_old_one_is_revoked(self, auth_service):
        user = await auth_service.register_business_owner(
            business_name="Store",
            full_name="Owner",
            email="rotate@example.com",
            password="Str0ngPass",
        )
        _, refresh_token = await auth_service.issue_token_pair(user)
        new_access, new_refresh = await auth_service.refresh_access_token(refresh_token)
        assert new_access != _
        assert new_refresh != refresh_token

        # Reusing the old refresh token must fail — it was revoked on rotation.
        with pytest.raises(InvalidTokenError):
            await auth_service.refresh_access_token(refresh_token)

    async def test_rejects_garbage_refresh_token(self, auth_service):
        with pytest.raises(InvalidTokenError):
            await auth_service.refresh_access_token("not-a-real-token")
