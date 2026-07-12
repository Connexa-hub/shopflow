from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)

# expire_on_commit=False is deliberate: it keeps attributes on committed
# objects accessible without triggering a lazy DB reload, which in async
# SQLAlchemy raises MissingGreenlet unless done through explicit
# eager-loading. Every query in this service that needs related data uses
# an explicit join instead of relying on lazy relationship loading — see
# app/domain/models.py for why relationships are deliberately omitted.
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
