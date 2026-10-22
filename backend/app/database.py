from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


settings = get_settings()

DATABASE_URL = settings.DATABASE_URL.get_secret_value()

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_timeout=30,
    pool_recycle=1800,
    echo=False,
)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy database models."""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session and always close it."""

    async with AsyncSessionFactory() as session:
        yield session


async def check_database_connection() -> bool:
    """Check whether the database is reachable."""

    from sqlalchemy import text

    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    return True


async def close_database() -> None:
    """Release database connection resources."""

    await engine.dispose()
