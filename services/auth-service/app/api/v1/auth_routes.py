from fastapi import APIRouter, HTTPException, status

from app.core.dependencies import AuthServiceDep
from app.core.logging import get_logger
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterBusinessOwnerRequest,
    TokenPairResponse,
    UserResponse,
)
from app.services.auth_service import (
    AccountLockedError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidTokenError,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = get_logger(__name__)


@router.post(
    "/register/business-owner",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_business_owner(
    body: RegisterBusinessOwnerRequest, auth_service: AuthServiceDep
) -> UserResponse:
    try:
        user = await auth_service.register_business_owner(
            business_name=body.business_name,
            full_name=body.full_name,
            email=body.email,
            password=body.password,
            phone_number=body.phone_number,
        )
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    logger.info("business_owner_registered", user_id=str(user.id))
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenPairResponse)
async def login(body: LoginRequest, auth_service: AuthServiceDep) -> TokenPairResponse:
    try:
        user = await auth_service.authenticate(email=body.email, password=body.password)
    except AccountLockedError as exc:
        raise HTTPException(status.HTTP_423_LOCKED, detail=str(exc)) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    access_token, refresh_token = await auth_service.issue_token_pair(user)
    logger.info("user_logged_in", user_id=str(user.id))
    return TokenPairResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(body: RefreshRequest, auth_service: AuthServiceDep) -> TokenPairResponse:
    try:
        access_token, refresh_token = await auth_service.refresh_access_token(
            body.refresh_token
        )
    except InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return TokenPairResponse(access_token=access_token, refresh_token=refresh_token)
