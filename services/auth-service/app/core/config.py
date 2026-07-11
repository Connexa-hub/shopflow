"""
auth-service specific settings. Extends the shared BaseServiceSettings so
it inherits fail-fast env validation, and adds fields unique to this
service (password hashing cost, lockout policy, etc.).
"""
from functools import lru_cache

from pydantic import Field
from shopflow_configuration import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = Field(default="auth-service")

    # Password / login policy
    bcrypt_rounds: int = Field(default=12)
    max_failed_login_attempts: int = Field(default=5)
    account_lockout_minutes: int = Field(default=15)

    # Multi-tenancy
    allow_self_signup: bool = Field(
        default=True,
        description="If true, a business_owner can self-register a new business.",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
