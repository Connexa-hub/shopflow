"""
Password hashing and JWT issuance/verification.

Password hashing calls the `bcrypt` package directly rather than going
through passlib's CryptContext. passlib's bcrypt backend detects the
installed bcrypt version by reading `bcrypt.__about__.__version__` — a
submodule bcrypt>=4.0 removed entirely. Without it, passlib falls back to
an internal self-calibration routine (`detect_wrap_bug`) that probes the
backend's behavior on overlong input; modern bcrypt deliberately raises
ValueError there instead of the old silent-wraparound behavior passlib's
probe expects, which crashes hashing before it ever touches an actual
password. passlib hasn't been updated for this in years (effectively
unmaintained) and the break is unconditional on first use, so pinning to
an older bcrypt was considered and rejected — it trades one known-fragile
dependency pairing for another. Calling bcrypt directly removes passlib
from the picture entirely; the API is small enough that passlib's
multi-algorithm abstraction wasn't buying much for a project that only
ever uses bcrypt.

Access tokens carry enough claims (user_id, business_id, role, permissions)
for downstream services to authorize a request WITHOUT calling back into
auth-service. This trades a slightly larger token for far lower latency and
no auth-service single point of failure on every request across the
platform.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

# bcrypt's underlying algorithm only uses the first 72 bytes of input —
# this is a property of the cipher itself (blowfish), not a passlib
# artifact. Older bcrypt implementations silently wrapped/ignored bytes
# past 72; bcrypt>=4.0 raises ValueError instead, on the reasoning that
# silent truncation is a security footgun. We truncate explicitly and
# predictably here rather than let a rare long-passphrase user hit a raw
# 500 error on registration. This operates on encoded bytes, not the
# Pydantic-level `max_length=128` character limit on the request schema —
# multi-byte UTF-8 characters mean 128 characters can exceed 72 bytes well
# before hitting that limit, so this is the actual authoritative guard for
# bcrypt's constraint specifically.
_BCRYPT_MAX_BYTES = 72


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(plain_password: str) -> str:
    settings = get_settings()
    password_bytes = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed/foreign hash format — treat as a failed verification
        # rather than crashing the login flow.
        return False


def create_access_token(
    *,
    user_id: str,
    business_id: str | None,
    role: str,
    permissions: list[str],
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "business_id": business_id,
        "role": role,
        "permissions": permissions,
        "type": TokenType.ACCESS.value,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(*, user_id: str) -> tuple[str, str]:
    """Returns (token, jti). The jti is stored (hashed) server-side so the
    token can be revoked — required for staff offboarding."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "type": TokenType.REFRESH.value,
        "iat": now,
        "exp": now + timedelta(days=settings.jwt_refresh_token_expire_days),
        "jti": jti,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, jti


class TokenError(Exception):
    pass


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise TokenError(str(exc)) from exc
