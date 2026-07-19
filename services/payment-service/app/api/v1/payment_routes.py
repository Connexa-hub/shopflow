import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from shopflow_constants import Permission

from app.core.dependencies import PaymentServiceDep
from app.core.security import BusinessContext, Principal, require_permission
from app.domain.models import PaymentStatus
from app.schemas.payment import InitializePaymentRequest, PaymentTransactionResponse
from app.services.payment_service import (
    PaymentNotFoundError,
    PaymentValidationError,
)

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])

CanInitiate = Annotated[Principal, Depends(require_permission(Permission.PAYMENTS_INITIATE))]
CanRead = Annotated[Principal, Depends(require_permission(Permission.PAYMENTS_READ))]


@router.post("", response_model=PaymentTransactionResponse, status_code=status.HTTP_201_CREATED)
async def initialize_payment(
    body: InitializePaymentRequest,
    business_id: BusinessContext,
    payment_service: PaymentServiceDep,
    _principal: CanInitiate,
) -> PaymentTransactionResponse:
    try:
        transaction = await payment_service.initialize_payment(
            business_id=business_id,
            provider=body.provider,
            amount=body.amount,
            currency=body.currency,
            customer_email=body.customer_email,
            purpose=body.purpose,
            related_sale_id=body.related_sale_id,
            customer_id=body.customer_id,
            metadata=body.metadata,
        )
    except PaymentValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PaymentTransactionResponse.model_validate(transaction)


@router.get("/{transaction_id}", response_model=PaymentTransactionResponse)
async def get_payment(
    transaction_id: uuid.UUID,
    business_id: BusinessContext,
    payment_service: PaymentServiceDep,
    _principal: CanRead,
) -> PaymentTransactionResponse:
    try:
        transaction = await payment_service.get_payment(
            business_id=business_id, transaction_id=transaction_id
        )
    except PaymentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PaymentTransactionResponse.model_validate(transaction)


@router.get("", response_model=list[PaymentTransactionResponse])
async def list_payments(
    business_id: BusinessContext,
    payment_service: PaymentServiceDep,
    _principal: CanRead,
    status_filter: PaymentStatus | None = Query(default=None, alias="status"),
    related_sale_id: uuid.UUID | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[PaymentTransactionResponse]:
    transactions = await payment_service.list_payments(
        business_id=business_id,
        status=status_filter,
        related_sale_id=related_sale_id,
        limit=limit,
        offset=offset,
    )
    return [PaymentTransactionResponse.model_validate(t) for t in transactions]


@router.post("/{transaction_id}/verify", response_model=PaymentTransactionResponse)
async def verify_payment(
    transaction_id: uuid.UUID,
    business_id: BusinessContext,
    payment_service: PaymentServiceDep,
    _principal: CanRead,
) -> PaymentTransactionResponse:
    """Active polling — the customer-facing callback page calls this
    rather than trusting redirect query params alone. Gated by
    PAYMENTS_READ, not INITIATE — checking status isn't creating a new
    charge."""
    try:
        transaction = await payment_service.verify_payment(
            business_id=business_id, transaction_id=transaction_id
        )
    except PaymentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PaymentValidationError as exc:
        # Can happen if a provider was disabled/misconfigured after a
        # transaction against it was already created — a real, if
        # unusual, edge case worth a clean 400 rather than a raw 500.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PaymentTransactionResponse.model_validate(transaction)
