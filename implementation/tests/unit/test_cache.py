"""Unit tests for cache module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from omnicast.cache.connection import init_redis, get_redis, close_redis
from omnicast.cache.rate_limiter import RateLimiter, claude_api_limiter, youtube_api_limiter
from omnicast.cache.distributed_lock import DistributedLock
from omnicast.cache.circuit_breaker import CircuitBreaker, CircuitState
from omnicast.shared.errors import CacheError, CircuitOpenError


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    with patch("omnicast.cache.connection._redis", redis):
        yield redis


@pytest.fixture
def mock_redis_with_lua(mock_redis):
    """Mock Redis with Lua script support."""
    mock_redis.script_load = AsyncMock(return_value="fake_sha")
    mock_redis.evalsha = AsyncMock(return_value=1)  # 1=allowed
    return mock_redis


class TestRateLimiter:
    """Tests for Token Bucket rate limiter."""

    @pytest.mark.asyncio
    async def test_acquire_success(self, mock_redis_with_lua):
        """Test acquire returns True when bucket has tokens."""
        limiter = RateLimiter("test", max_tokens=10, refill_rate=5, refill_interval=60)
        result = await limiter.acquire(1)
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_empty_bucket(self, mock_redis_with_lua):
        """Test acquire returns False when bucket is empty."""
        mock_redis_with_lua.evalsha = AsyncMock(return_value=0)  # 0=not allowed
        limiter = RateLimiter("test", max_tokens=10, refill_rate=5, refill_interval=60)
        result = await limiter.acquire(1)
        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_multiple_tokens(self, mock_redis_with_lua):
        """Test acquiring multiple tokens."""
        limiter = RateLimiter("test", max_tokens=10, refill_rate=5, refill_interval=60)
        result = await limiter.acquire(3)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_remaining(self, mock_redis):
        """Test get_remaining returns current token count."""
        mock_redis.hmget = AsyncMock(return_value=["7.5", "123456"])
        limiter = RateLimiter("test", max_tokens=10, refill_rate=5, refill_interval=60)
        remaining = await limiter.get_remaining()
        assert remaining == 7

    @pytest.mark.asyncio
    async def test_get_remaining_default(self, mock_redis):
        """Test get_remaining returns max_tokens when key doesn't exist."""
        mock_redis.hmget = AsyncMock(return_value=[None, None])
        limiter = RateLimiter("test", max_tokens=10, refill_rate=5, refill_interval=60)
        remaining = await limiter.get_remaining()
        assert remaining == 10

    @pytest.mark.asyncio
    async def test_reset(self, mock_redis):
        """Test reset deletes the key."""
        limiter = RateLimiter("test", max_tokens=10, refill_rate=5, refill_interval=60)
        await limiter.reset()
        mock_redis.delete.assert_called_once_with("ratelimit:test")

    def test_factory_claude(self):
        """Test claude_api_limiter factory."""
        limiter = claude_api_limiter()
        assert limiter.name == "claude_api"
        assert limiter.max_tokens == 50
        assert limiter.refill_rate == 50
        assert limiter.refill_interval == 60

    def test_factory_youtube(self):
        """Test youtube_api_limiter factory."""
        limiter = youtube_api_limiter("channel123")
        assert limiter.name == "youtube_api_channel123"
        assert limiter.max_tokens == 10000
        assert limiter.refill_rate == 10000
        assert limiter.refill_interval == 86400


class TestDistributedLock:
    """Tests for distributed lock."""

    @pytest.mark.asyncio
    async def test_acquire_and_release(self, mock_redis):
        """Test acquire sets key, release deletes it."""
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.script_load = AsyncMock(return_value="sha")
        mock_redis.evalsha = AsyncMock(return_value=1)

        lock = DistributedLock("test_lock")
        acquired = await lock.acquire()
        assert acquired is True
        mock_redis.set.assert_called_once()

        await lock.release()
        mock_redis.evalsha.assert_called_once()

    @pytest.mark.asyncio
    async def test_lock_already_held(self, mock_redis):
        """Test acquire returns False when key exists."""
        mock_redis.set = AsyncMock(return_value=None)  # NX failed
        lock = DistributedLock("test_lock")
        acquired = await lock.acquire()
        assert acquired is False

    @pytest.mark.asyncio
    async def test_release_lua_script(self, mock_redis):
        """Test release uses Lua script for atomicity."""
        mock_redis.script_load = AsyncMock(return_value="sha")
        mock_redis.evalsha = AsyncMock(return_value=1)

        lock = DistributedLock("test_lock")
        await lock.release()

        mock_redis.script_load.assert_called_once()
        mock_redis.evalsha.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_retries(self, mock_redis):
        """Test context manager retries on failure."""
        call_count = [0]

        async def mock_set(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                return None  # Fail first 2 times
            return True  # Succeed on 3rd

        mock_redis.set = mock_set
        mock_redis.script_load = AsyncMock(return_value="sha")
        mock_redis.evalsha = AsyncMock(return_value=1)

        lock = DistributedLock("test_lock", retry_interval=0.01, max_retries=5)
        async with lock:
            assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_context_manager_max_retries(self, mock_redis):
        """Test context manager raises after max retries."""
        mock_redis.set = AsyncMock(return_value=None)
        lock = DistributedLock("test_lock", retry_interval=0.01, max_retries=3)

        with pytest.raises(CacheError, match="Lock acquisition failed"):
            async with lock:
                pass


class TestCircuitBreaker:
    """Tests for circuit breaker."""

    @pytest.mark.asyncio
    async def test_closed_allows_calls(self, mock_redis):
        """Test CLOSED state allows calls."""
        mock_redis.get = AsyncMock(return_value=None)
        cb = CircuitBreaker("test_cb")
        async with cb:
            pass  # Should not raise

    @pytest.mark.asyncio
    async def test_open_blocks_calls(self, mock_redis):
        """Test OPEN state blocks calls."""
        mock_redis.get = AsyncMock(return_value="open")
        mock_redis.set = AsyncMock()
        cb = CircuitBreaker("test_cb", recovery_timeout=60)

        with pytest.raises(CircuitOpenError, match="Service unavailable"):
            async with cb:
                pass

    @pytest.mark.asyncio
    async def test_transitions_to_open(self, mock_redis):
        """Test transitions to OPEN after threshold failures."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.incr = AsyncMock(return_value=3)
        mock_redis.set = AsyncMock()

        cb = CircuitBreaker("test_cb", failure_threshold=3)
        await cb.record_failure()

        mock_redis.set.assert_called()

    @pytest.mark.asyncio
    async def test_transitions_to_half_open(self, mock_redis):
        """Test transitions to HALF_OPEN after recovery timeout."""
        mock_redis.get = AsyncMock(side_effect=lambda k: "open" if "state" in k else "100.0")
        mock_redis.set = AsyncMock()

        cb = CircuitBreaker("test_cb", recovery_timeout=60)
        state = await cb.get_state()

        assert state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self, mock_redis):
        """Test success in HALF_OPEN closes circuit."""
        mock_redis.get = AsyncMock(return_value="half_open")
        mock_redis.set = AsyncMock()
        mock_redis.delete = AsyncMock()

        cb = CircuitBreaker("test_cb")
        await cb.record_success()

        mock_redis.set.assert_called()
        mock_redis.delete.assert_called()

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self, mock_redis):
        """Test failure in HALF_OPEN reopens circuit."""
        mock_redis.get = AsyncMock(return_value="half_open")
        mock_redis.set = AsyncMock()

        cb = CircuitBreaker("test_cb")
        await cb.record_failure()

        mock_redis.set.assert_called()

    @pytest.mark.asyncio
    async def test_context_manager_records_success(self, mock_redis):
        """Test context manager records success on no exception."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        mock_redis.delete = AsyncMock()

        cb = CircuitBreaker("test_cb")
        async with cb:
            pass  # No exception

        mock_redis.set.assert_called()

    @pytest.mark.asyncio
    async def test_context_manager_records_failure(self, mock_redis):
        """Test context manager records failure on exception."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.set = AsyncMock()

        cb = CircuitBreaker("test_cb", failure_threshold=5)

        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("test error")

        mock_redis.incr.assert_called()

    @pytest.mark.asyncio
    async def test_is_open_property(self, mock_redis):
        """Test is_open property returns True when OPEN."""
        mock_redis.get = AsyncMock(return_value="open")
        cb = CircuitBreaker("test_cb")
        is_open = await cb.is_open
        assert is_open is True

    @pytest.mark.asyncio
    async def test_is_open_property_false_when_closed(self, mock_redis):
        """Test is_open property returns False when CLOSED."""
        mock_redis.get = AsyncMock(return_value=None)
        cb = CircuitBreaker("test_cb")
        is_open = await cb.is_open
        assert is_open is False