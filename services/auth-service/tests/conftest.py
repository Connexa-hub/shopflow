import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Required env vars must be set BEFORE app.core.config is imported anywhere,
# since Settings() validates at instantiation time.
os.environ.setdefault("SERVICE_NAME", "auth-service")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only-do-not-use-in-prod")
os.environ.setdefault("ENVIRONMENT", "test")

from app.domain.base import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories.token_repository import TokenRepository  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core import dependencies  # noqa: E402


@pytest_asyncio.fixture
async def db_session():
    # Fresh in-memory SQLite DB per test — fast, isolated, no shared state.
    engine = create_async_engine(f"sqlite+aiosqlite:///file:{uuid.uuid4()}?mode=memory&cache=shared&uri=true")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def auth_service(db_session) -> AuthService:
    return AuthService(
        user_repo=UserRepository(db_session),
        token_repo=TokenRepository(db_session),
        settings=get_settings(),
    )


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_db_session():
        yield db_session

    from app.core.database import get_db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
