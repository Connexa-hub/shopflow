"""inventory-service entrypoint. Settings validate (fail-fast) at import time."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.category_routes import router as category_router
from app.api.v1.health_routes import router as health_router
from app.api.v1.location_routes import router as location_router
from app.api.v1.product_routes import router as product_router
from app.api.v1.stock_routes import router as stock_router
from app.api.v1.supplier_routes import router as supplier_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging()
logger = get_logger(__name__)

app = FastAPI(
    title="ShopFlow Inventory Service",
    description="Product catalog, stock ledger, and multi-location inventory for ShopFlow.",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(product_router)
app.include_router(category_router)
app.include_router(location_router)
app.include_router(supplier_router)
app.include_router(stock_router)


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("inventory_service_starting", environment=settings.environment.value)
