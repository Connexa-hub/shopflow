"""
auth-service entrypoint.

Settings are loaded (and validated) at import time via get_settings(), so
the process fails fast on boot if a required env var is missing — before
it ever accepts traffic.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.auth_routes import router as auth_router
from app.api.v1.health_routes import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging()
logger = get_logger(__name__)

app = FastAPI(
    title="ShopFlow Auth Service",
    description="Authentication, JWT issuance, and RBAC for the ShopFlow platform.",
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
app.include_router(auth_router)


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("auth_service_starting", environment=settings.environment.value)
