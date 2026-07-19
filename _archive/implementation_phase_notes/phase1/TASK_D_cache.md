# TASK D: Cache Layer (Redis + Circuit Breaker + Rate Limiter)

> **Depends on:** TASK_A hoàn thành (shared/errors.py có RateLimitError, CircuitOpenError, CacheError)
> **Output:** src/omnicast/cache/, tests/unit/test_cache.py
> **Parallel với:** TASK_B, C, E, F, G

## Context

Redis dùng cho 3 mục đích:
1. **Rate Limiter** — Token Bucket algorithm, giới hạn API calls (Claude, YouTube)
2. **Distributed Lock** — tránh 5 Workers cùng generate 1 asset
3. **Circuit Breaker** — auto-fallback khi external service down

Module KHÔNG dùng cho caching data (PostgreSQL đủ cho Phase 1).

## Files cần tạo

```
src/omnicast/cache/
├── __init__.py
├── connection.py          # Redis connection
├── rate_limiter.py        # Token Bucket
├── distributed_lock.py    # Redis-based distributed lock
└── circuit_breaker.py     # Circuit Breaker pattern
```

## 1. connection.py

```python
"""Redis async connection management.

Usage:
    await init_redis("redis://localhost:6379/0")
    redis = get_redis()
    await redis.set("key", "value")
    await close_redis()
"""

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

_redis: aioredis.Redis | None = None
```

### Functions

```python
async def init_redis(url: str) -> None:
    """Initialize Redis connection pool.
    
    - Create Redis instance with decode_responses=True
    - Ping to verify connection
    - Log: "Redis connected"
    - Raises CacheError if connection fails
    """

def get_redis() -> aioredis.Redis:
    """Return Redis instance. Raises CacheError if not initialized."""

async def close_redis() -> None:
    """Close Redis connection pool."""
```

## 2. rate_limiter.py — Token Bucket Algorithm

```python
"""Distributed rate limiter using Redis + Token Bucket.

Mỗi Agent/API consumer phải xin token trước khi gọi external API.
Đảm bảo không vượt quá TPM/RPM khi nhiều Workers chạy song song.

Usage:
    limiter = RateLimiter(name="claude_api", max_tokens=50, refill_rate=10, refill_interval=60)
    if await limiter.acquire():
        # call Claude API
    else:
        raise RateLimitError("Claude API rate limit exceeded")
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
    
    async def acquire(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Return True if allowed, False if rate limited.
        
        Algorithm (execute as Lua script for atomicity):
        1. Get current bucket state from Redis hash:
           {tokens: float, last_refill: float(timestamp)}
        2. Calculate elapsed time since last_refill
        3. Add refill tokens: min(max_tokens, current + elapsed/interval * refill_rate)
        4. If tokens >= requested:
             tokens -= requested
             Update Redis hash
             Return True
        5. Else:
             Return False (don't consume)
        
        CRITICAL: Must use Lua script — Python code is NOT atomic across Workers.
        """
    
    async def get_remaining(self) -> int:
        """Return current token count (for dashboard display)."""
    
    async def reset(self) -> None:
        """Reset bucket to max_tokens. For testing/emergency."""

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
```

### Predefined Rate Limiters

```python
# Factory functions cho common use cases
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

## 3. distributed_lock.py

```python
"""Redis-based distributed lock.

Tránh race condition khi nhiều Workers cùng:
- Generate cùng 1 asset
- Update cùng 1 record
- Process cùng 1 video task

Usage:
    lock = DistributedLock("asset_gen:cinematic_001")
    async with lock:
        # Only 1 worker executes this block
        await generate_music(mood="cinematic")
"""

import uuid

class DistributedLock:
    """Redis-based distributed lock with auto-expiry.
    
    Args:
        name: lock identifier (must be unique per resource)
        timeout: max lock hold time in seconds (auto-release after this)
        retry_interval: seconds between retry attempts
        max_retries: max retry attempts before giving up
    """
    
    def __init__(
        self,
        name: str,
        timeout: int = 300,       # 5 min default
        retry_interval: float = 0.5,
        max_retries: int = 20,
    ):
        self.key = f"lock:{name}"
        self.timeout = timeout
        self.retry_interval = retry_interval
        self.max_retries = max_retries
        self.token = str(uuid.uuid4())  # Unique per acquisition
    
    async def acquire(self) -> bool:
        """Try to acquire lock.
        
        Implementation:
        - redis.set(key, token, nx=True, ex=timeout)
        - nx=True → only set if not exists (atomic)
        - ex=timeout → auto-expire (prevent deadlock)
        - Return True if acquired, False if already held
        """
    
    async def release(self) -> None:
        """Release lock IF we still own it.
        
        CRITICAL: Must use Lua script to check-and-delete atomically:
          if redis.get(key) == our_token then redis.del(key)
        
        Nếu dùng GET then DEL riêng → race condition:
          Worker A: GET → sees own token
          Worker B: SET (lock expired, B acquired)
          Worker A: DEL → deletes B's lock!
        """
    
    async def __aenter__(self) -> "DistributedLock":
        """Context manager: acquire with retries.
        
        - Loop max_retries times
        - If acquire() returns True → return self
        - Else → asyncio.sleep(retry_interval) → retry
        - If all retries fail → raise CacheError("Lock acquisition failed: {name}")
        """
    
    async def __aexit__(self, *args) -> None:
        """Release lock."""

# Lua script for safe release
RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""
```

## 4. circuit_breaker.py

```python
"""Circuit Breaker pattern for external service calls.

States:
  CLOSED  → normal operation, calls pass through
  OPEN    → service down, calls fail fast (raise CircuitOpenError)
  HALF_OPEN → testing recovery, allow 1 call through

Usage:
    breaker = CircuitBreaker("claude_api", failure_threshold=3, recovery_timeout=300)
    
    async with breaker:
        response = await call_claude_api(prompt)
    # breaker auto-records success/failure
    
    # Or check state:
    if breaker.is_open:
        # use fallback (Ollama)
"""

from enum import StrEnum

class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class CircuitBreaker:
    """Redis-backed circuit breaker.
    
    State stored in Redis (shared across all Workers):
      circuit:{name}:state       → "closed" | "open" | "half_open"
      circuit:{name}:failures    → int (consecutive failure count)
      circuit:{name}:last_failure → timestamp
      circuit:{name}:half_open_call → bool (is someone testing recovery?)
    
    Args:
        name: service identifier (e.g. "claude_api", "youtube_api")
        failure_threshold: consecutive failures to open circuit (default 3)
        recovery_timeout: seconds before trying again (default 300 = 5 min)
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: int = 300,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.prefix = f"circuit:{name}"
    
    async def get_state(self) -> CircuitState:
        """Get current state from Redis.
        
        Logic:
        1. Read state from Redis
        2. If state == OPEN:
           - Check if recovery_timeout has passed
           - If yes → transition to HALF_OPEN
        3. Return state
        """
    
    async def record_success(self) -> None:
        """Record successful call.
        
        - Reset failure count to 0
        - Set state to CLOSED
        - Log if transitioning from HALF_OPEN → CLOSED ("Circuit recovered")
        """
    
    async def record_failure(self) -> None:
        """Record failed call.
        
        - Increment failure count
        - If failure count >= threshold:
          - Set state to OPEN
          - Set last_failure timestamp
          - Log: "Circuit OPEN for {name} after {count} failures"
        """
    
    @property
    async def is_open(self) -> bool:
        """Return True if circuit is OPEN (should use fallback)."""
    
    async def __aenter__(self) -> "CircuitBreaker":
        """Check state before allowing call.
        
        - CLOSED → allow
        - OPEN → raise CircuitOpenError(name, "Service unavailable, circuit open")
        - HALF_OPEN → allow ONE call (set half_open_call flag)
        """
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Record result based on whether exception occurred.
        
        - No exception → record_success()
        - Exception → record_failure()
        - Return False (don't suppress exception)
        """
```

## 5. Tests

### tests/unit/test_cache.py

```python
"""Test cache utilities with mocked Redis.

=== RateLimiter Tests ===

test_acquire_success:
    - Bucket full (50 tokens)
    - acquire(1) → True
    - Remaining = 49

test_acquire_empty_bucket:
    - Bucket at 0 tokens
    - acquire(1) → False

test_refill_logic:
    - Set last_refill to 120s ago, refill_interval=60, refill_rate=10
    - Expected: 20 tokens refilled
    - acquire(15) → True

test_acquire_multiple_tokens:
    - Bucket has 5 tokens
    - acquire(3) → True, remaining = 2
    - acquire(3) → False (only 2 left)

=== DistributedLock Tests ===

test_acquire_and_release:
    - acquire() → True
    - Key exists in Redis with token value
    - release() → key deleted

test_lock_already_held:
    - Set key in Redis (simulating another worker holding lock)
    - acquire() → False

test_release_only_own_lock:
    - Set key with different token (another worker's lock)
    - release() → key NOT deleted (Lua script check)

test_context_manager_retries:
    - First acquire fails, second succeeds
    - Context manager enters successfully

test_context_manager_max_retries_exceeded:
    - All acquire attempts fail
    - Raises CacheError

test_auto_expiry:
    - Acquire with timeout=1
    - Wait 2s
    - Key expired → another worker can acquire

=== CircuitBreaker Tests ===

test_closed_allows_calls:
    - State = CLOSED
    - __aenter__ → no exception

test_open_blocks_calls:
    - State = OPEN, last_failure recent
    - __aenter__ → raises CircuitOpenError

test_transitions_to_open:
    - Record 3 failures (threshold=3)
    - State → OPEN

test_transitions_to_half_open:
    - State = OPEN, last_failure > recovery_timeout ago
    - get_state() → HALF_OPEN

test_half_open_success_closes:
    - State = HALF_OPEN
    - record_success()
    - State → CLOSED

test_half_open_failure_reopens:
    - State = HALF_OPEN
    - record_failure()
    - State → OPEN

test_context_manager_records_success:
    - async with breaker: pass (no exception)
    - Verify record_success called

test_context_manager_records_failure:
    - async with breaker: raise ConnectionError
    - Verify record_failure called
    - Exception still propagates
"""
```

## 6. DO NOT

- ❌ Đừng implement Token Bucket bằng Python code thuần — PHẢI dùng Lua script (atomicity)
- ❌ Đừng dùng GET-then-DEL cho lock release — PHẢI dùng Lua script (race condition)
- ❌ Đừng dùng redis-py sync — dùng redis.asyncio
- ❌ Đừng store circuit state trong memory — PHẢI dùng Redis (shared across Workers)
- ❌ Đừng quên auto-expiry trên locks — timeout bắt buộc (prevent deadlock)
- ❌ Đừng catch exceptions trong circuit breaker __aexit__ — return False để exception propagate

## 7. Acceptance Criteria

```bash
uv run pytest tests/unit/test_cache.py -v
uv run pyright src/omnicast/cache/
```
