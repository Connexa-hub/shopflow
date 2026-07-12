import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Must be set before app.core.config is imported anywhere (Settings()
# validates at instantiation time — same pattern as auth-service).
os.environ.setdefault("SERVICE_NAME", "inventory-service")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only-do-not-use-in-prod")
os.environ.setdefault("ENVIRONMENT", "test")

from shopflow_constants import DEFAULT_ROLE_PERMISSIONS, Role  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_db_session  # noqa: E402
from app.domain.base import Base  # noqa: E402
from app.main import app  # noqa: E402


def make_access_token(
    *, business_id: uuid.UUID | None, role: Role, user_id: uuid.UUID | None = None
) -> str:
    """Fabricates a token with the exact shape auth-service issues. Used
    instead of importing auth-service (services stay independently
    deployable/testable — the JWT claims contract is the integration
    point, not shared code)."""
    settings = get_settings()
    permissions = [p.value for p in DEFAULT_ROLE_PERMISSIONS.get(role, frozenset())]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id or uuid.uuid4()),
        "business_id": str(business_id) if business_id else None,
        "role": role.value,
        "permissions": permissions,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:{uuid.uuid4()}?mode=memory&cache=shared&uri=true"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
def business_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest_asyncio.fixture
def owner_headers(business_id):
    token = make_access_token(business_id=business_id, role=Role.BUSINESS_OWNER)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
def cashier_headers(business_id):
    token = make_access_token(business_id=business_id, role=Role.CASHIER)
    return {"Authorization": f"Bearer {token}"}
