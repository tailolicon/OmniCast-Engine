"""Circuit breaker pattern using Redis for OmniCast Engine."""

from __future__ import annotations

import time
from enum import StrEnum

import structlog

from omnicast.cache.connection import get_redis
from omnicast.shared.errors import CacheError, CircuitOpenError

logger = structlog.get_logger()


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


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

    @property
    async def is_open(self) -> bool:
        """Return True if circuit is OPEN (should use fallback)."""
        state = await self.get_state()
        return state == CircuitState.OPEN

    async def get_state(self) -> CircuitState:
        redis = get_redis()
        state = await redis.get(f"{self.prefix}:state")
        if state is None:
            return CircuitState.CLOSED

        if state == CircuitState.OPEN:
            last_failure = await redis.get(f"{self.prefix}:last_failure")
            if last_failure is not None:
                try:
                    elapsed = time.time() - float(last_failure)
                    if elapsed >= self.recovery_timeout:
                        await redis.set(f"{self.prefix}:state", CircuitState.HALF_OPEN)
                        return CircuitState.HALF_OPEN
                except (ValueError, TypeError):
                    pass  # last_failure not a valid timestamp, skip recovery check
        return CircuitState(state)

    async def __aenter__(self) -> "CircuitBreaker":
        try:
            redis = get_redis()
        except CacheError:
            logger.warning("Circuit breaker unavailable (Redis not connected), bypassing", name=self.name)
            return self
        state = await self.get_state()
        if state == CircuitState.CLOSED:
            return self
        if state == CircuitState.OPEN:
            raise CircuitOpenError(f"Service unavailable: {self.name}, circuit open")
        # HALF_OPEN — allow ONE call
        allowed = await redis.set(
            f"{self.prefix}:half_open_call", "1", nx=True, ex=self.recovery_timeout
        )
        if not allowed:
            raise CircuitOpenError(self.name, "Circuit half-open, another call testing recovery")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        try:
            redis = get_redis()
        except CacheError:
            return False  # Redis unavailable, skip tracking
        await redis.delete(f"{self.prefix}:half_open_call")
        if exc_type is not None:
            await self.record_failure()
        else:
            await self.record_success()
        return False  # Don't suppress exception

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