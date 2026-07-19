from functools import lru_cache

from pydantic import Field
from shopflow_configuration import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = Field(default="payment-service")

    # Public base URL this service is reachable at, used to build each
    # provider's callback/redirect URL at initialize time. In docker-
    # compose this is the internal service URL; in production it should
    # be the public API gateway URL, since the customer's browser (not
    # another backend service) is what gets redirected there.
    public_base_url: str = Field(...)

    # Provider credentials. All optional at the Settings level — a
    # deployment might only enable one or two providers, not all three;
    # PaymentService raises PaymentValidationError at call time if a
    # request names a provider with no configured credentials, rather
    # than failing at startup for a provider nobody's using yet.
    paystack_secret_key: str | None = Field(default=None)
    paystack_base_url: str = Field(default="https://api.paystack.co")

    flutterwave_secret_key: str | None = Field(default=None)
    flutterwave_secret_hash: str | None = Field(default=None)
    flutterwave_base_url: str = Field(default="https://api.flutterwave.com/v3")

    monnify_api_key: str | None = Field(default=None)
    monnify_secret_key: str | None = Field(default=None)
    monnify_contract_code: str | None = Field(default=None)
    monnify_base_url: str = Field(default="https://api.monnify.com")


@lru_cache
def get_settings() -> Settings:
    return Settings()
