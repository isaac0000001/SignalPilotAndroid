from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


# SQLAlchemy model base
class Base(DeclarativeBase):
    pass


# Application settings
settings = get_settings()
DATABASE_URL = settings.DATABASE_URL


# Configure asynchronous database drivers
if DATABASE_URL.startswith("sqlite://"):
    DATABASE_URL = DATABASE_URL.replace(
        "sqlite://",
        "sqlite+aiosqlite://",
        1,
    )
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql+asyncpg://",
        1,
    )
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1,
    )


# Create asynchronous database engine
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
)


# Create session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# Database dependency used by API routes
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# Compatibility with existing imports
async def get_database() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db():
        yield session


# Close database connections on shutdown
async def close_database() -> None:
    await engine.dispose()
