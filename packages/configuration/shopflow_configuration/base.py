"""
Shared base configuration for all ShopFlow services.

Every service defines its own Settings class that extends BaseServiceSettings
and adds service-specific fields. Pydantic validates types and required-ness
at import time, so a service will refuse to start rather than run with a
missing secret. This is intentional: silent misconfiguration in a payments
or auth path is worse than a crash-on-boot.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class BaseServiceSettings(BaseSettings):
    """Common settings every ShopFlow service requires.

    Service-specific settings classes should inherit from this and add
    their own fields. Do NOT put service-specific secrets here.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Identity ---
    service_name: str = Field(..., description="Unique service identifier, e.g. 'auth-service'")
    environment: Environment = Field(default=Environment.DEVELOPMENT)

    # --- Networking ---
    port: int = Field(default=8000)
    host: str = Field(default="0.0.0.0")

    # --- Core infra (required in staging/production) ---
    database_url: str = Field(..., description="Postgres connection string")
    redis_url: str = Field(..., description="Redis connection string")

    # --- Security ---
    jwt_secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=15)
    jwt_refresh_token_expire_days: int = Field(default=30)

    # --- Observability ---
    log_level: str = Field(default="INFO")

    @field_validator("jwt_secret_key")
    @classmethod
    def _reject_placeholder_secret(cls, v: str) -> str:
        placeholders = {"changeme", "secret", "your-secret-key-here", ""}
        if v.strip().lower() in placeholders:
            raise ValueError(
                "jwt_secret_key is set to a placeholder value. "
                "Generate a real secret (e.g. `openssl rand -hex 32`) before starting."
            )
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION


@lru_cache
def get_base_settings(settings_cls: type[BaseServiceSettings]) -> BaseServiceSettings:
    """Cached settings loader. Pass your service's Settings subclass.

    Raises pydantic.ValidationError immediately if required env vars are
    missing or malformed — this is the "fail fast on missing critical
    environment variables" requirement.
    """
    return settings_cls()
