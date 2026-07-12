from functools import lru_cache

from pydantic import Field
from shopflow_configuration import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = Field(default="inventory-service")

    # Stock policy
    allow_negative_stock: bool = Field(
        default=False,
        description=(
            "If false (default), a movement that would take a product's stock "
            "below zero at a location is rejected. Some businesses (e.g. "
            "pre-order/backorder models) may want this relaxed later — kept "
            "as a setting rather than hardcoded so it doesn't require a code "
            "change per Phase 1's 'no developer assistance' merchant config goal."
        ),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
