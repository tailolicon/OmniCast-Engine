"""Redis async connection management.

Usage:
    await init_redis("redis://localhost:6379/0")
    redis = get_redis()
    await redis.set("key", "value")
    await close_redis()
"""

from __future__ import annotations

import redis.asyncio as aioredis
import structlog

from omnicast.shared.errors import CacheError

logger = structlog.get_logger()

_redis: aioredis.Redis | None = None


async def init_redis(url: str) -> None:
    """Initialize Redis connection pool.

    - Create Redis instance with decode_responses=True
    - Ping to verify connection
    - Log: "Redis connected"
    - Raises CacheError if connection fails
    """
    global _redis
    try:
        _redis = aioredis.from_url(url, decode_responses=True)
        await _redis.ping()
        logger.info("Redis connected", url=url.split("@")[-1])  # Don't log password
    except Exception as exc:
        raise CacheError(f"Failed to connect to Redis: {exc}") from exc


def get_redis() -> aioredis.Redis:
    """Return Redis instance. Raises CacheError if not initialized."""
    if _redis is None:
        raise CacheError("Redis not initialized. Call init_redis() first.")
    return _redis


async def close_redis() -> None:
    """Close Redis connection pool."""
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
        logger.info("Redis connection closed")