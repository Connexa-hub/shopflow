"""
Business logic for authentication. This is the only layer that knows
"what happens" — repositories only know "how to fetch/store".
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from shopflow_constants import DEFAULT_ROLE_PERMISSIONS, Role

from app.core.config import Settings
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.domain.models import Business, RefreshToken, User
from app.repositories.token_repository import TokenRepository
from app.repositories.user_repository import UserRepository


class AuthError(Exception):
    """Base class for expected auth failures (bad credentials, locked
    account, etc.) — mapped to HTTP responses at the API layer."""


class InvalidCredentialsError(AuthError):
    pass


class AccountLockedError(AuthError):
    pass


class EmailAlreadyRegisteredError(AuthError):
    pass


class InvalidTokenError(AuthError):
    pass


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or str(uuid.uuid4())[:8]


class AuthService:
    def __init__(
        self,
        user_repo: UserRepository,
        token_repo: TokenRepository,
        settings: Settings,
    ):
        self._users = user_repo
        self._tokens = token_repo
        self._settings = settings

    async def register_business_owner(
        self,
        *,
        business_name: str,
        full_name: str,
        email: str,
        password: str,
        phone_number: str | None = None,
    ) -> User:
        existing = await self._users.get_by_email(email)
        if existing is not None:
            raise EmailAlreadyRegisteredError(f"{email} is already registered")

        business = Business(name=business_name, slug=_slugify(business_name))
        user = User(
            business=business,
            email=email.lower(),
            full_name=full_name,
            phone_number=phone_number,
            hashed_password=hash_password(password),
            role=Role.BUSINESS_OWNER.value,
        )
        created = await self._users.create(user)
        await self._users.commit()
        return created

    async def authenticate(self, *, email: str, password: str) -> User:
        user = await self._users.get_by_email(email)
        if user is None:
            raise InvalidCredentialsError("Invalid email or password")

        if user.failed_login_attempts >= self._settings.max_failed_login_attempts:
            raise AccountLockedError(
                "Account locked due to too many failed attempts. "
                f"Try again in {self._settings.account_lockout_minutes} minutes "
                "or contact support."
            )

        if not verify_password(password, user.hashed_password):
            user.failed_login_attempts += 1
            await self._users.update(user)
            await self._users.commit()
            raise InvalidCredentialsError("Invalid email or password")

        if not user.is_active:
            raise InvalidCredentialsError("Account is deactivated")

        user.failed_login_attempts = 0
        await self._users.update(user)
        await self._users.commit()
        return user

    async def issue_token_pair(self, user: User) -> tuple[str, str]:
        role = Role(user.role)
        permissions = [p.value for p in DEFAULT_ROLE_PERMISSIONS.get(role, frozenset())]

        access_token = create_access_token(
            user_id=str(user.id),
            business_id=str(user.business_id) if user.business_id else None,
            role=user.role,
            permissions=permissions,
        )
        refresh_token, jti = create_refresh_token(user_id=str(user.id))

        expires_at = datetime.now(timezone.utc).isoformat()
        await self._tokens.create(
            RefreshToken(user_id=user.id, jti=jti, expires_at=expires_at)
        )
        await self._tokens.commit()
        return access_token, refresh_token

    async def refresh_access_token(self, refresh_token: str) -> tuple[str, str]:
        try:
            payload = decode_token(refresh_token)
        except TokenError as exc:
            raise InvalidTokenError("Invalid or expired refresh token") from exc

        if payload.get("type") != "refresh":
            raise InvalidTokenError("Token is not a refresh token")

        stored = await self._tokens.get_by_jti(payload["jti"])
        if stored is None or stored.revoked:
            raise InvalidTokenError("Refresh token has been revoked")

        user = await self._users.get_by_id(uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise InvalidTokenError("User no longer active")

        # Rotate: revoke the old refresh token, issue a new pair.
        await self._tokens.revoke(stored)
        await self._tokens.commit()
        return await self.issue_token_pair(user)
