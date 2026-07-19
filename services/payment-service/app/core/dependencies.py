"""FastAPI dependency providers — composition root for DI."""
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.domain.models import PaymentProvider
from app.providers.base import PaymentProviderProtocol
from app.providers.flutterwave import FlutterwaveAdapter
from app.providers.monnify import MonnifyAdapter
from app.providers.paystack import PaystackAdapter
from app.repositories.payment_repository import PaymentRepository
from app.services.payment_service import PaymentService

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@lru_cache
def get_provider_registry() -> dict[PaymentProvider, PaymentProviderProtocol]:
    """Only providers with configured credentials are registered — a
    deployment might enable just Paystack, for instance, and calling
    PaymentService with an unregistered provider raises a clear
    PaymentValidationError rather than the adapter crashing on a missing
    secret_key at construction time."""
    settings = get_settings()
    registry: dict[PaymentProvider, PaymentProviderProtocol] = {}

    if settings.paystack_secret_key:
        registry[PaymentProvider.PAYSTACK] = PaystackAdapter(
            secret_key=settings.paystack_secret_key, base_url=settings.paystack_base_url
        )

    if settings.flutterwave_secret_key and settings.flutterwave_secret_hash:
        registry[PaymentProvider.FLUTTERWAVE] = FlutterwaveAdapter(
            secret_key=settings.flutterwave_secret_key,
            secret_hash=settings.flutterwave_secret_hash,
            base_url=settings.flutterwave_base_url,
        )

    if settings.monnify_api_key and settings.monnify_secret_key and settings.monnify_contract_code:
        registry[PaymentProvider.MONNIFY] = MonnifyAdapter(
            api_key=settings.monnify_api_key,
            secret_key=settings.monnify_secret_key,
            contract_code=settings.monnify_contract_code,
            base_url=settings.monnify_base_url,
        )

    return registry


ProviderRegistryDep = Annotated[
    dict[PaymentProvider, PaymentProviderProtocol], Depends(get_provider_registry)
]


def get_payment_service(
    session: DbSession,
    providers: ProviderRegistryDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PaymentService:
    return PaymentService(
        PaymentRepository(session), providers, callback_base_url=settings.public_base_url
    )


PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]
