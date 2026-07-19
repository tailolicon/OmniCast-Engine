# TASK D FIX: Cache Layer — Rewrite 3 Files

> **Severity:** CRITICAL — wrong algorithm, race condition, wrong API
> **Files to rewrite:** `rate_limiter.py`, `distributed_lock.py`
> **Files to update:** `connection.py`, `circuit_breaker.py`, `__init__.py`, `tests/unit/test_cache.py`
> **Estimated time:** 45 min

## Problem Summary

| File | Issue |
|------|-------|
| `connection.py` | Wrong function names (`init_cache`/`get_cache` vs spec's `init_redis`/`get_redis`) |
| `rate_limiter.py` | Wrong algorithm (Sliding Window instead of Token Bucket), no Lua script, wrong interface |
| `distributed_lock.py` | Race condition in `release()` — GET-then-DELETE instead of atomic Lua script |
| `circuit_breaker.py` | Minor: missing `is_open`, wrong defaults, no HALF_OPEN single-call guard |

---

## 1. Rewrite `connection.py`

Delete current `_CacheManager` class. Replace with simple module-level functions matching spec:

```python
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
```

**Key changes:** Remove `_CacheManager` class, `get_session()`, `CacheConnectionError`, `CacheNotInitializedError`. Simple module globals like spec.

---

## 2. Rewrite `rate_limiter.py`

Delete everything. Replace with Token Bucket + Lua script:

```python
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
```

---

## 3. Fix `distributed_lock.py`

### 3a. Add Lua script for atomic release

Add this constant at module level:

```python
# Lua script for safe release — check-and-delete atomically
RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""
```

### 3b. Change constructor — use `get_redis()` instead of injected client

```python
from omnicast.cache.connection import get_redis
from omnicast.shared.errors import CacheError

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
```

### 3c. Rewrite `acquire()` to use `get_redis()`

```python
    async def acquire(self) -> bool:
        """Try to acquire lock. Return True if acquired, False if held."""
        redis = get_redis()
        result = await redis.set(
            self.key, self.token, nx=True, ex=self.timeout
        )
        return result is True  # SET NX returns True or None
```

### 3d. Rewrite `release()` with Lua script

```python
    async def release(self) -> None:
        """Release lock IF we still own it. Uses Lua script for atomicity."""
        redis = get_redis()
        if self._release_sha is None:
            self._release_sha = await redis.script_load(RELEASE_LOCK_SCRIPT)
        await redis.evalsha(self._release_sha, 1, self.key, self.token)
```

### 3e. Fix `__aenter__` to retry

```python
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
```

---

## 4. Fix `circuit_breaker.py`

### 4a. Use `StrEnum` instead of `str, Enum`

```python
from enum import StrEnum

class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
```

### 4b. Change constructor — use `get_redis()`, fix defaults

```python
from omnicast.cache.connection import get_redis

class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,      # was 5
        recovery_timeout: int = 300,     # was 60
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.prefix = f"circuit:{name}"
```

Remove `redis_client` parameter. Use `get_redis()` internally in each method.

### 4c. Add `is_open` property

```python
    @property
    async def is_open(self) -> bool:
        """Return True if circuit is OPEN (should use fallback)."""
        state = await self.get_state()
        return state == CircuitState.OPEN
```

### 4d. Fix `get_state()` — auto-transition OPEN → HALF_OPEN

```python
    async def get_state(self) -> CircuitState:
        redis = get_redis()
        state = await redis.get(f"{self.prefix}:state")
        if state is None:
            return CircuitState.CLOSED

        if state == CircuitState.OPEN:
            last_failure = await redis.get(f"{self.prefix}:last_failure")
            if last_failure is not None:
                elapsed = time.time() - float(last_failure)
                if elapsed >= self.recovery_timeout:
                    await redis.set(f"{self.prefix}:state", CircuitState.HALF_OPEN)
                    return CircuitState.HALF_OPEN
        return CircuitState(state)
```

### 4e. Add HALF_OPEN single-call guard

In `__aenter__`, for HALF_OPEN state, use Redis SETNX on `{prefix}:half_open_call` to allow only ONE caller through:

```python
    async def __aenter__(self) -> "CircuitBreaker":
        redis = get_redis()
        state = await self.get_state()
        if state == CircuitState.CLOSED:
            return self
        if state == CircuitState.OPEN:
            raise CircuitOpenError(self.name, "Service unavailable, circuit open")
        # HALF_OPEN — allow ONE call
        allowed = await redis.set(
            f"{self.prefix}:half_open_call", "1", nx=True, ex=self.recovery_timeout
        )
        if not allowed:
            raise CircuitOpenError(self.name, "Circuit half-open, another call testing recovery")
        return self
```

### 4f. Fix `__aexit__` — explicit `return False`

```python
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        redis = get_redis()
        await redis.delete(f"{self.prefix}:half_open_call")
        if exc_type is not None:
            await self.record_failure()
        else:
            await self.record_success()
        return False  # Don't suppress exception
```

### 4g. Fix `record_success` and `record_failure`

Use `get_redis()` instead of `self._redis`:

```python
    async def record_success(self) -> None:
        redis = get_redis()
        state = await self.get_state()
        await redis.set(f"{self.prefix}:state", CircuitState.CLOSED)
        await redis.delete(f"{self.prefix}:failures")
        if state == CircuitState.HALF_OPEN:
            logger.info("Circuit recovered", name=self.name)

    async def record_failure(self) -> None:
        redis = get_redis()
        state = await self.get_state()
        if state == CircuitState.HALF_OPEN:
            await redis.set(f"{self.prefix}:state", CircuitState.OPEN)
            await redis.set(f"{self.prefix}:last_failure", str(time.time()))
            logger.warning("Circuit re-opened from half-open", name=self.name)
            return
        failures = await redis.incr(f"{self.prefix}:failures")
        if failures >= self.failure_threshold:
            await redis.set(f"{self.prefix}:state", CircuitState.OPEN)
            await redis.set(f"{self.prefix}:last_failure", str(time.time()))
            logger.warning("Circuit OPEN", name=self.name, failures=failures)
```

---

## 5. Update `__init__.py`

```python
"""Cache/Redis module for OmniCast Engine."""

from omnicast.cache.connection import init_redis, get_redis, close_redis
from omnicast.cache.rate_limiter import RateLimiter, claude_api_limiter, youtube_api_limiter
from omnicast.cache.distributed_lock import DistributedLock
from omnicast.cache.circuit_breaker import CircuitBreaker, CircuitState

__all__ = [
    "init_redis",
    "get_redis",
    "close_redis",
    "RateLimiter",
    "claude_api_limiter",
    "youtube_api_limiter",
    "DistributedLock",
    "CircuitBreaker",
    "CircuitState",
]
```

---

## 6. Rewrite `tests/unit/test_cache.py`

Rewrite tests to match new interfaces. Key test cases:

### RateLimiter Tests
```
test_acquire_success — bucket full, acquire(1) → True
test_acquire_empty_bucket — bucket at 0, acquire(1) → False
test_refill_logic — last_refill 120s ago, refill_interval=60, refill_rate=10 → 20 tokens refilled
test_acquire_multiple_tokens — bucket=5, acquire(3)→True remaining=2, acquire(3)→False
test_get_remaining — returns current token count
test_reset — deletes key
test_factory_claude — claude_api_limiter() returns RateLimiter with correct params
test_factory_youtube — youtube_api_limiter("ch1") returns RateLimiter with correct params
```

### DistributedLock Tests
```
test_acquire_and_release — acquire→True, key exists, release→key deleted
test_lock_already_held — key exists with different token → acquire→False
test_release_only_own_lock — Lua script check: different token → key NOT deleted
test_context_manager_retries — first acquire fails, second succeeds
test_context_manager_max_retries — all fail → raises CacheError
```

### CircuitBreaker Tests
```
test_closed_allows_calls — state=CLOSED → __aenter__ ok
test_open_blocks_calls — state=OPEN, recent failure → raises CircuitOpenError
test_transitions_to_open — 3 failures (threshold=3) → state=OPEN
test_transitions_to_half_open — state=OPEN, last_failure > recovery_timeout → HALF_OPEN
test_half_open_success_closes — record_success in HALF_OPEN → CLOSED
test_half_open_failure_reopens — record_failure in HALF_OPEN → OPEN
test_context_manager_records_success — no exception → record_success called
test_context_manager_records_failure — exception → record_failure called, exception propagates
test_is_open_property — returns True when OPEN
```

### Mock Strategy

Mock `get_redis()` to return a `MagicMock`/`AsyncMock`:

```python
@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    with patch("omnicast.cache.connection._redis", redis):
        yield redis
```

For Lua script tests, mock `redis.evalsha()` and `redis.script_load()`:

```python
@pytest.fixture
def mock_redis_with_lua(mock_redis):
    mock_redis.script_load = AsyncMock(return_value="fake_sha")
    mock_redis.evalsha = AsyncMock(return_value=1)  # 1=allowed
    return mock_redis
```

---

## Verify

```bash
uv run pytest tests/unit/test_cache.py -v
uv run pyright src/omnicast/cache/
```

## DO NOT

- Do NOT change `shared/errors.py`
- Do NOT add new error subclasses (use existing `CacheError`, `RateLimitError`, `CircuitOpenError`)
- Do NOT use redis-py sync — always `redis.asyncio`
- Do NOT implement Token Bucket in Python — MUST use Lua script
- Do NOT use GET-then-DEL for lock release — MUST use Lua script
