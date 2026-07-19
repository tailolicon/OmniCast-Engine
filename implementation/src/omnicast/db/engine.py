"""Async PostgreSQL engine + session factory.

Usage:
    init_db("postgresql+asyncpg://user:pass@localhost/dbname")
    async with get_session() as session:
        result = await session.execute(select(ChannelORM))
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
import structlog

from omnicast.shared.errors import ConfigError

logger = structlog.get_logger()

# Singleton engine — initialized once via init_db()
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(
    database_url: str,
    pool_size: int = 5,
    max_overflow: int = 10,
) -> None:
    """Initialize global engine + session factory. Call once at startup.

    Args:
        database_url: PostgreSQL connection string (postgresql+asyncpg://...)
        pool_size: Base connection pool size
        max_overflow: Max additional connections

    Raises:
        ConfigError: if database_url is empty or invalid format
    """
    global _engine, _session_factory

    if not database_url or not database_url.strip():
        raise ConfigError("database_url cannot be empty")

    if "postgresql+asyncpg://" not in database_url:
        raise ConfigError(
            f"Invalid database_url format. Expected 'postgresql+asyncpg://...', got: {database_url[:30]}..."
        )

    _engine = create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        echo=False,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    logger.info(
        "Database engine initialized",
        pool_size=pool_size,
        max_overflow=max_overflow,
    )


def get_engine() -> AsyncEngine:
    """Return initialized engine. Raises ConfigError if init_db() not called."""
    if _engine is None:
        raise ConfigError("Database not initialized. Call init_db() first.")
    return _engine


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session. Auto-commit on success, rollback on exception.

    Usage:
        async with get_session() as session:
            channel = await session.get(ChannelORM, 1)

    Raises:
        ConfigError: if init_db() not called
    """
    if _session_factory is None:
        raise ConfigError("Database not initialized. Call init_db() first.")

    session = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def close_db() -> None:
    """Dispose engine. Call at shutdown."""
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
        logger.info("Database engine disposed")

    _engine = None
    _session_factory = None