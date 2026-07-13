"""FastAPI dependency providers — composition root for DI."""
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.inventory_client import HttpInventoryClient, InventoryClientProtocol
from app.repositories.sale_repository import SaleRepository
from app.services.sale_service import SaleService

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@lru_cache
def get_inventory_client() -> InventoryClientProtocol:
    """A single HttpInventoryClient instance is reused across requests —
    it holds no per-request state (each call opens its own httpx.AsyncClient
    context), so there's no reason to construct a new one per request."""
    settings = get_settings()
    return HttpInventoryClient(
        settings.inventory_service_url,
        timeout_seconds=settings.inventory_service_timeout_seconds,
    )


InventoryClientDep = Annotated[InventoryClientProtocol, Depends(get_inventory_client)]


def get_sale_service(
    session: DbSession, inventory_client: InventoryClientDep
) -> SaleService:
    return SaleService(SaleRepository(session), inventory_client)


SaleServiceDep = Annotated[SaleService, Depends(get_sale_service)]
