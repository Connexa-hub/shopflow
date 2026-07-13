from functools import lru_cache

from pydantic import Field
from shopflow_configuration import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = Field(default="sales-service")

    inventory_service_url: str = Field(
        ...,
        description=(
            "Base URL for inventory-service, e.g. 'http://inventory-service:8000' "
            "inside docker-compose or 'http://localhost:8002' for local dev outside "
            "Docker. Required — sales-service cannot function without it."
        ),
    )
    inventory_service_timeout_seconds: float = Field(default=10.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
