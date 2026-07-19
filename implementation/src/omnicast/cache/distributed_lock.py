"""Distributed lock using Redis for OmniCast Engine."""

from __future__ import annotations

import asyncio
import uuid

import structlog

from omnicast.cache.connection import get_redis
from omnicast.shared.errors import CacheError

logger = structlog.get_logger()

# Lua script for safe release — check-and-delete atomically
RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


class DistributedLock:
    """Redis-based distributed lock with auto-expiry."""

    def __init__(
        self,
        name: str,
        timeout: int = 300,        # 5 min default (was 30s!)
        retry_interval: float = 0.5,
        max_retries: int = 20,
    ):
        self.key = f"lock:{name}"
        self.timeout = timeout
        self.retry_interval = retry_interval
        self.max_retries = max_retries
        self.token = str(uuid.uuid4())  # Unique per acquisition
        self._release_sha: str | None = None

    async def acquire(self) -> bool:
        """Try to acquire lock. Return True if acquired, False if held."""
        redis = get_redis()
        result = await redis.set(
            self.key, self.token, nx=True, ex=self.timeout
        )
        return result is True  # SET NX returns True or None

    async def release(self) -> None:
        """Release lock IF we still own it. Uses Lua script for atomicity."""
        redis = get_redis()
        if self._release_sha is None:
            self._release_sha = await redis.script_load(RELEASE_LOCK_SCRIPT)
        await redis.evalsha(self._release_sha, 1, self.key, self.token)

    async def __aenter__(self) -> "DistributedLock":
        """Context manager: acquire with retries."""
        for _ in range(self.max_retries):
            if await self.acquire():
                return self
            await asyncio.sleep(self.retry_interval)
        raise CacheError(f"Lock acquisition failed: {self.key}")

    async def __aexit__(self, *args) -> None:
        """Release lock."""
        await self.release()