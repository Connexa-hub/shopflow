"""FastAPI dependency providers — the composition root for DI."""
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.repositories.category_repository import CategoryRepository
from app.repositories.location_repository import LocationRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.stock_repository import StockRepository
from app.repositories.supplier_repository import SupplierRepository
from app.services.category_service import CategoryService
from app.services.location_service import LocationService
from app.services.product_service import ProductService
from app.services.stock_service import StockService
from app.services.supplier_service import SupplierService

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_product_service(session: DbSession) -> ProductService:
    return ProductService(
        ProductRepository(session), CategoryRepository(session), SupplierRepository(session)
    )


def get_category_service(session: DbSession) -> CategoryService:
    return CategoryService(CategoryRepository(session))


def get_location_service(session: DbSession) -> LocationService:
    return LocationService(LocationRepository(session))


def get_supplier_service(session: DbSession) -> SupplierService:
    return SupplierService(SupplierRepository(session))


def get_stock_service(session: DbSession, settings: SettingsDep) -> StockService:
    return StockService(
        StockRepository(session),
        ProductRepository(session),
        LocationRepository(session),
        allow_negative_stock=settings.allow_negative_stock,
    )


ProductServiceDep = Annotated[ProductService, Depends(get_product_service)]
CategoryServiceDep = Annotated[CategoryService, Depends(get_category_service)]
LocationServiceDep = Annotated[LocationService, Depends(get_location_service)]
SupplierServiceDep = Annotated[SupplierService, Depends(get_supplier_service)]
StockServiceDep = Annotated[StockService, Depends(get_stock_service)]
