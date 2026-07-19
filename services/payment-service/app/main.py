"""
payment-service entrypoint. Settings are loaded (and validated) at import
time via get_settings(), so the process fails fast on boot if a required
env var — including public_base_url, which every provider's callback URL
depends on — is missing. Provider credentials themselves are optional at
the Settings level (see core/dependencies.py's get_provider_registry) —
a deployment enabling only one or two providers is a valid configuration,
not a startup failure.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health_routes import router as health_router
from app.api.v1.payment_routes import router as payment_router
from app.api.v1.webhook_routes import router as webhook_router
from app.core.config import get_settings
from app.core.dependencies import get_provider_registry
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging()
logger = get_logger(__name__)

app = FastAPI(
    title="ShopFlow Payment Service",
    description="Provider-agnostic payment adapters: Paystack, Flutterwave, Monnify.",
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
app.include_router(payment_router)
app.include_router(webhook_router)


@app.on_event("startup")
async def on_startup() -> None:
    enabled_providers = list(get_provider_registry().keys())
    logger.info(
        "payment_service_starting",
        environment=settings.environment.value,
        enabled_providers=[p.value for p in enabled_providers],
    )
