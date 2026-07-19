"""Distributed rate limiter using Redis + Token Bucket.

Usage:
    limiter = RateLimiter(name="claude_api", max_tokens=50, refill_rate=10, refill_interval=60)
    if await limiter.acquire():
        # call Claude API
    else:
        raise RateLimitError("Claude API rate limit exceeded")
"""

from __future__ import annotations

import time

import structlog

from omnicast.cache.connection import get_redis

logger = structlog.get_logger()

# Lua script for atomic token bucket
TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local max_tokens = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local refill_interval = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local now = tonumber(ARGV[5])

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1]) or max_tokens
local last_refill = tonumber(bucket[2]) or now

-- Refill
local elapsed = now - last_refill
local refill = math.floor(elapsed / refill_interval) * refill_rate
if refill > 0 then
    tokens = math.min(max_tokens, tokens + refill)
    last_refill = now
end

-- Try consume
if tokens >= requested then
    tokens = tokens - requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    redis.call('EXPIRE', key, refill_interval * 10)
    return 1
else
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    redis.call('EXPIRE', key, refill_interval * 10)
    return 0
end
"""


class RateLimiter:
    """Token Bucket rate limiter backed by Redis.

    Args:
        name: unique identifier (e.g. "claude_api", "youtube_api_channel_fin_us")
        max_tokens: bucket capacity
        refill_rate: tokens added per refill
        refill_interval: seconds between refills
    """

    def __init__(
        self,
        name: str,
        max_tokens: int,
        refill_rate: int,
        refill_interval: int = 60,
    ):
        self.name = name
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self.refill_interval = refill_interval
        self.key = f"ratelimit:{name}"
        self._script_sha: str | None = None

    async def _get_script_sha(self) -> str:
        """Load Lua script into Redis and cache SHA."""
        if self._script_sha is None:
            redis = get_redis()
            self._script_sha = await redis.script_load(TOKEN_BUCKET_SCRIPT)
        return self._script_sha

    async def acquire(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Return True if allowed, False if rate limited.

        Uses Lua script for atomicity across multiple Workers.
        """
        redis = get_redis()
        now = time.time()

        try:
            sha = await self._get_script_sha()
            result = await redis.evalsha(
                sha,
                1,  # num keys
                self.key,  # KEYS[1]
                self.max_tokens,  # ARGV[1]
                self.refill_rate,  # ARGV[2]
                self.refill_interval,  # ARGV[3]
                tokens,  # ARGV[4]
                now,  # ARGV[5]
            )
            allowed = result == 1
            if not allowed:
                logger.debug("Rate limited", name=self.name, requested=tokens)
            return allowed
        except Exception:
            # If script not loaded (e.g. Redis restarted), reload
            self._script_sha = None
            sha = await self._get_script_sha()
            result = await redis.evalsha(
                sha, 1, self.key,
                self.max_tokens, self.refill_rate, self.refill_interval,
                tokens, now,
            )
            return result == 1

    async def get_remaining(self) -> int:
        """Return current token count (for dashboard display)."""
        redis = get_redis()
        data = await redis.hmget(self.key, "tokens", "last_refill")
        tokens = float(data[0]) if data[0] is not None else self.max_tokens
        return int(tokens)

    async def reset(self) -> None:
        """Reset bucket to max_tokens. For testing/emergency."""
        redis = get_redis()
        await redis.delete(self.key)


# Factory functions
def claude_api_limiter() -> RateLimiter:
    """Claude API: 50 requests/minute."""
    return RateLimiter("claude_api", max_tokens=50, refill_rate=50, refill_interval=60)


def youtube_api_limiter(channel_id: str) -> RateLimiter:
    """YouTube API: 10,000 units/day per channel project."""
    return RateLimiter(
        f"youtube_api_{channel_id}",
        max_tokens=10000, refill_rate=10000, refill_interval=86400,
    )