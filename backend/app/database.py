from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


settings = get_settings()

# DATABASE_URL is a regular string in the current configuration.
DATABASE_URL = settings.DATABASE_URL

# Create the database engine.
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
)

# Create an asynchronous session factory.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_database() -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session to an API request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def close_database() -> None:
    """Dispose of database connections during application shutdown."""
    await engine.dispose()
