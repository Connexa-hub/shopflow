"""Async SQLAlchemy engine + session factory."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)

# expire_on_commit=False deliberately — see auth-service's Phase 1 notes:
# without it, accessing an attribute after commit re-triggers a lazy load,
# which is unsafe in async SQLAlchemy unless explicitly awaited.
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
