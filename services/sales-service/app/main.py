"""
sales-service entrypoint. Settings are loaded (and validated) at import
time via get_settings(), so the process fails fast on boot if a required
env var — including inventory_service_url, which this service cannot
function without — is missing.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health_routes import router as health_router
from app.api.v1.sale_routes import router as sale_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging()
logger = get_logger(__name__)

app = FastAPI(
    title="ShopFlow Sales Service",
    description="POS transaction engine: sales, line items, payments, and voids.",
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
app.include_router(sale_router)


@app.on_event("startup")
async def on_startup() -> None:
    logger.info(
        "sales_service_starting",
        environment=settings.environment.value,
        inventory_service_url=settings.inventory_service_url,
    )
