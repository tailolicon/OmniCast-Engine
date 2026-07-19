# TASK_A: LLM Client + Agent Base

## Model: sonnet
## Estimated time: 45 minutes
## Dependencies: None (Phase 1 must be complete)

## Overview

Build the LLM client wrapper around Anthropic SDK and the base agent class.
All other agents (Writer, Critic, etc.) inherit from BaseAgent.

LLM Client handles: API calls, rate limiting (via Phase 1 RateLimiter),
circuit breaking (via Phase 1 CircuitBreaker), cost tracking, dry-run mode.

## Files

| File | Lines | Description |
|------|------:|-------------|
| `src/omnicast/llm/__init__.py` | ~5 | Exports |
| `src/omnicast/llm/client.py` | ~180 | Claude API wrapper |
| `src/omnicast/llm/fallback.py` | ~60 | Dry-run and Ollama fallback |
| `src/omnicast/llm/cost.py` | ~100 | Token counting + cost calc |
| `src/omnicast/agents/__init__.py` | ~5 | Exports |
| `src/omnicast/agents/base.py` | ~120 | BaseAgent abstract class |
| `tests/unit/test_llm_client.py` | ~200 | Pre-written tests |
| `tests/unit/test_agent_base.py` | ~120 | Pre-written tests |

## Context Files (read before implementing)

- `src/omnicast/config/settings.py` — Settings (claude_api_key, claude_model, claude_rpm_limit, daily_llm_budget_usd)
- `src/omnicast/cache/rate_limiter.py` — RateLimiter, claude_api_limiter()
- `src/omnicast/cache/circuit_breaker.py` — CircuitBreaker
- `src/omnicast/shared/errors.py` — AgentError
- `src/omnicast/models/enums.py` — Niche, Market

## Interface Definitions

### src/omnicast/llm/client.py

```python
"""Claude API client with rate limiting, circuit breaking, and cost tracking."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from omnicast.config.settings import get_settings
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


@dataclass(frozen=True)
class LLMResponse:
    """Immutable response from LLM call."""
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    stop_reason: str


class LLMClient:
    """Async Claude API client.

    Features:
    - Rate limiting via Phase 1 RateLimiter
    - Circuit breaker via Phase 1 CircuitBreaker
    - Automatic cost tracking per call
    - Dry-run mode returns mock response
    - Structured output via tool_use (optional)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> None:
        """
        If api_key is None, reads from Settings.
        If model is None, reads from Settings.
        If Settings.is_dry_run, use DryRunClient internally.
        """
        raise NotImplementedError

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send completion request to Claude API.

        Steps:
        1. Check rate limiter (acquire token)
        2. Enter circuit breaker context
        3. Call anthropic.AsyncAnthropic.messages.create()
        4. Build LLMResponse with cost calculation
        5. Log with structlog (model, tokens, cost)
        6. Return response

        Raises:
            AgentError: on API error, rate limit, circuit open
        """
        raise NotImplementedError

    async def complete_structured(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        output_schema: type,
        max_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> tuple[LLMResponse, object]:
        """
        Send request expecting structured JSON output.
        Uses Anthropic tool_use to enforce schema.

        Returns:
            Tuple of (raw LLMResponse, parsed Pydantic object)

        Raises:
            AgentError: on parse failure or API error
        """
        raise NotImplementedError

    @property
    def total_cost(self) -> float:
        """Accumulated cost across all calls in this client instance."""
        raise NotImplementedError

    @property
    def total_tokens(self) -> int:
        """Accumulated tokens (input + output)."""
        raise NotImplementedError
```

### src/omnicast/llm/fallback.py

```python
"""Fallback LLM clients for dry-run and Ollama."""

from omnicast.llm.client import LLMResponse


class DryRunClient:
    """Returns deterministic mock responses. For testing and dry_run mode."""

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Return mock LLMResponse with content='[DRY RUN] ...'"""
        raise NotImplementedError

    async def complete_structured(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        output_schema: type,
        max_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> tuple[LLMResponse, object]:
        """Return mock response + default instance of output_schema."""
        raise NotImplementedError
```

### src/omnicast/llm/cost.py

```python
"""Token counting and cost calculation for Claude models."""

from __future__ import annotations

from dataclasses import dataclass


# Claude pricing (per million tokens)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # model: (input_per_mtok, output_per_mtok)
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
    "claude-opus-4-5": (15.0, 75.0),
}


@dataclass(frozen=True)
class CostBreakdown:
    """Immutable cost breakdown for a single LLM call."""
    model: str
    input_tokens: int
    output_tokens: int
    input_cost: float
    output_cost: float
    total_cost: float


class CostCalculator:
    """Calculate and accumulate LLM costs."""

    def calculate(self, model: str, input_tokens: int, output_tokens: int) -> CostBreakdown:
        """
        Calculate cost for a single call.
        Unknown models default to claude-sonnet-4-6 pricing.
        """
        raise NotImplementedError

    def accumulate(self, breakdown: CostBreakdown) -> None:
        """Add to running total."""
        raise NotImplementedError

    @property
    def total_cost(self) -> float:
        raise NotImplementedError

    @property
    def total_input_tokens(self) -> int:
        raise NotImplementedError

    @property
    def total_output_tokens(self) -> int:
        raise NotImplementedError

    def summary(self) -> dict[str, float]:
        """Return per-model cost breakdown."""
        raise NotImplementedError
```

### src/omnicast/agents/base.py

```python
"""Base agent class for all OmniCast agents."""

from __future__ import annotations

from abc import ABC, abstractmethod

import structlog

from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


class BaseAgent(ABC):
    """Abstract base for all agents.

    Lifecycle: __init__ → execute() → result logged via structlog

    Subclasses implement:
    - name property (agent identifier)
    - system_prompt property (system message for LLM)
    - execute() method (main logic)
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._call_count: int = 0

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent identifier for logging/metrics."""
        ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt sent to LLM."""
        ...

    async def call_llm(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Call LLM with agent's system prompt.
        Wraps LLMClient.complete with agent-level logging.

        Steps:
        1. Increment call count
        2. Log call start (agent name, message count)
        3. Call self._llm.complete(system=self.system_prompt, ...)
        4. Log response (tokens, cost)
        5. Return LLMResponse

        Raises: AgentError on LLM failure
        """
        raise NotImplementedError

    async def call_llm_structured(
        self,
        messages: list[dict[str, str]],
        output_schema: type,
        *,
        max_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> tuple[LLMResponse, object]:
        """Call LLM expecting structured output. Wraps complete_structured."""
        raise NotImplementedError

    @abstractmethod
    async def execute(self, *args, **kwargs):
        """Main agent logic. Subclasses implement this."""
        ...

    @property
    def cost(self) -> float:
        """Total LLM cost for this agent instance."""
        return self._llm.total_cost

    @property
    def call_count(self) -> int:
        return self._call_count
```

## DO NOT

- ❌ Do not import `anthropic` at module level — import inside methods (lazy) for testability
- ❌ Do not create a real Anthropic client in tests — always mock
- ❌ Do not use sync `anthropic.Anthropic` — use `anthropic.AsyncAnthropic`
- ❌ Do not hardcode API keys — read from Settings
- ❌ Do not swallow exceptions — wrap in AgentError with context
- ❌ Do not use `print()` — use `structlog`

## Pre-Written Tests

### tests/unit/test_llm_client.py

```python
"""Tests for LLM client wrapper."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.llm.fallback import DryRunClient
from omnicast.llm.cost import CostCalculator, CostBreakdown, MODEL_PRICING
from omnicast.shared.errors import AgentError


# === CostCalculator Tests ===


class TestCostCalculator:
    def test_calculate_sonnet(self):
        calc = CostCalculator()
        result = calc.calculate("claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
        assert isinstance(result, CostBreakdown)
        assert result.model == "claude-sonnet-4-6"
        assert result.input_tokens == 1000
        assert result.output_tokens == 500
        # 1000 * 3.0 / 1_000_000 = 0.003
        assert result.input_cost == pytest.approx(0.003, abs=1e-6)
        # 500 * 15.0 / 1_000_000 = 0.0075
        assert result.output_cost == pytest.approx(0.0075, abs=1e-6)
        assert result.total_cost == pytest.approx(0.0105, abs=1e-6)

    def test_calculate_haiku(self):
        calc = CostCalculator()
        result = calc.calculate("claude-haiku-4-5", input_tokens=2000, output_tokens=1000)
        # 2000 * 0.80 / 1M = 0.0016, 1000 * 4.0 / 1M = 0.004
        assert result.input_cost == pytest.approx(0.0016, abs=1e-6)
        assert result.output_cost == pytest.approx(0.004, abs=1e-6)

    def test_calculate_unknown_model_defaults_sonnet(self):
        calc = CostCalculator()
        result = calc.calculate("claude-unknown-99", input_tokens=1000, output_tokens=500)
        # Should use sonnet pricing as fallback
        assert result.input_cost == pytest.approx(0.003, abs=1e-6)

    def test_accumulate(self):
        calc = CostCalculator()
        b1 = calc.calculate("claude-sonnet-4-6", 1000, 500)
        b2 = calc.calculate("claude-haiku-4-5", 2000, 1000)
        calc.accumulate(b1)
        calc.accumulate(b2)
        assert calc.total_cost == pytest.approx(b1.total_cost + b2.total_cost, abs=1e-6)
        assert calc.total_input_tokens == 3000
        assert calc.total_output_tokens == 1500

    def test_summary_per_model(self):
        calc = CostCalculator()
        calc.accumulate(calc.calculate("claude-sonnet-4-6", 1000, 500))
        calc.accumulate(calc.calculate("claude-haiku-4-5", 2000, 1000))
        summary = calc.summary()
        assert "claude-sonnet-4-6" in summary
        assert "claude-haiku-4-5" in summary


# === DryRunClient Tests ===


class TestDryRunClient:
    async def test_complete_returns_mock(self):
        client = DryRunClient()
        response = await client.complete(
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hello"}],
        )
        assert isinstance(response, LLMResponse)
        assert "[DRY RUN]" in response.content
        assert response.cost_usd == 0.0
        assert response.input_tokens == 0
        assert response.output_tokens == 0

    async def test_complete_structured_returns_defaults(self):
        from pydantic import BaseModel

        class TestOutput(BaseModel):
            score: int = 0
            feedback: str = ""

        client = DryRunClient()
        response, parsed = await client.complete_structured(
            system="Judge.",
            messages=[{"role": "user", "content": "Rate this."}],
            output_schema=TestOutput,
        )
        assert isinstance(response, LLMResponse)
        assert isinstance(parsed, TestOutput)
        assert parsed.score == 0


# === LLMClient Tests ===


class TestLLMClient:
    @pytest.fixture
    def mock_settings(self, monkeypatch):
        """Mock settings for LLMClient."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x@localhost/db")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost/")
        monkeypatch.setenv("CLAUDE_API_KEY", "sk-test-key")
        monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-4-6")
        monkeypatch.setenv("OMNICAST_MODE", "staging")
        from omnicast.config.settings import reset_settings
        reset_settings()

    @pytest.fixture
    def mock_rate_limiter(self):
        limiter = AsyncMock()
        limiter.acquire.return_value = True
        return limiter

    @pytest.fixture
    def mock_anthropic_response(self):
        """Mock anthropic.types.Message."""
        msg = MagicMock()
        msg.content = [MagicMock(text="Hello from Claude", type="text")]
        msg.model = "claude-sonnet-4-6"
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 50
        msg.stop_reason = "end_turn"
        return msg

    async def test_complete_success(
        self, mock_settings, mock_rate_limiter, mock_anthropic_response
    ):
        with patch("omnicast.llm.client.claude_api_limiter", return_value=mock_rate_limiter):
            with patch("omnicast.llm.client.CircuitBreaker") as MockCB:
                cb_instance = AsyncMock()
                cb_instance.__aenter__ = AsyncMock(return_value=cb_instance)
                cb_instance.__aexit__ = AsyncMock(return_value=False)
                MockCB.return_value = cb_instance

                client = LLMClient(api_key="sk-test")
                # Mock the internal anthropic client
                client._anthropic = AsyncMock()
                client._anthropic.messages.create = AsyncMock(
                    return_value=mock_anthropic_response
                )

                response = await client.complete(
                    system="You are helpful.",
                    messages=[{"role": "user", "content": "Hello"}],
                )
                assert isinstance(response, LLMResponse)
                assert response.content == "Hello from Claude"
                assert response.input_tokens == 100
                assert response.output_tokens == 50
                assert response.cost_usd > 0

    async def test_complete_rate_limited(self, mock_settings):
        mock_limiter = AsyncMock()
        mock_limiter.acquire.return_value = False
        with patch("omnicast.llm.client.claude_api_limiter", return_value=mock_limiter):
            client = LLMClient(api_key="sk-test")
            with pytest.raises(AgentError, match="rate limit"):
                await client.complete(
                    system="test",
                    messages=[{"role": "user", "content": "hi"}],
                )

    async def test_dry_run_mode(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x@localhost/db")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost/")
        monkeypatch.setenv("OMNICAST_MODE", "dry_run")
        from omnicast.config.settings import reset_settings
        reset_settings()

        client = LLMClient()
        response = await client.complete(
            system="test",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert "[DRY RUN]" in response.content
        assert response.cost_usd == 0.0

    async def test_total_cost_accumulates(self, mock_settings, mock_anthropic_response):
        mock_limiter = AsyncMock()
        mock_limiter.acquire.return_value = True
        with patch("omnicast.llm.client.claude_api_limiter", return_value=mock_limiter):
            with patch("omnicast.llm.client.CircuitBreaker") as MockCB:
                cb = AsyncMock()
                cb.__aenter__ = AsyncMock(return_value=cb)
                cb.__aexit__ = AsyncMock(return_value=False)
                MockCB.return_value = cb

                client = LLMClient(api_key="sk-test")
                client._anthropic = AsyncMock()
                client._anthropic.messages.create = AsyncMock(
                    return_value=mock_anthropic_response
                )

                await client.complete(
                    system="test", messages=[{"role": "user", "content": "1"}]
                )
                await client.complete(
                    system="test", messages=[{"role": "user", "content": "2"}]
                )
                assert client.total_cost > 0
                assert client.total_tokens == 300  # (100+50) * 2
```

### tests/unit/test_agent_base.py

```python
"""Tests for BaseAgent."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.shared.errors import AgentError


class ConcreteAgent(BaseAgent):
    """Concrete implementation for testing."""

    @property
    def name(self) -> str:
        return "test_agent"

    @property
    def system_prompt(self) -> str:
        return "You are a test agent."

    async def execute(self, input_text: str) -> str:
        response = await self.call_llm(
            [{"role": "user", "content": input_text}]
        )
        return response.content


class TestBaseAgent:
    @pytest.fixture
    def mock_llm(self) -> AsyncMock:
        llm = AsyncMock(spec=LLMClient)
        llm.complete.return_value = LLMResponse(
            content="test response",
            model="claude-sonnet-4-6",
            input_tokens=50,
            output_tokens=25,
            cost_usd=0.000525,
            stop_reason="end_turn",
        )
        llm.total_cost = 0.000525
        return llm

    @pytest.fixture
    def agent(self, mock_llm) -> ConcreteAgent:
        return ConcreteAgent(llm=mock_llm)

    async def test_call_llm_delegates(self, agent, mock_llm):
        response = await agent.call_llm(
            [{"role": "user", "content": "hello"}]
        )
        assert response.content == "test response"
        mock_llm.complete.assert_called_once()
        call_kwargs = mock_llm.complete.call_args
        assert call_kwargs.kwargs["system"] == "You are a test agent."

    async def test_call_count_increments(self, agent):
        assert agent.call_count == 0
        await agent.call_llm([{"role": "user", "content": "1"}])
        assert agent.call_count == 1
        await agent.call_llm([{"role": "user", "content": "2"}])
        assert agent.call_count == 2

    async def test_execute_uses_call_llm(self, agent):
        result = await agent.execute("test input")
        assert result == "test response"

    async def test_llm_error_raises_agent_error(self, mock_llm):
        mock_llm.complete.side_effect = AgentError("LLM failed")
        agent = ConcreteAgent(llm=mock_llm)
        with pytest.raises(AgentError, match="LLM failed"):
            await agent.call_llm([{"role": "user", "content": "fail"}])

    async def test_name_property(self, agent):
        assert agent.name == "test_agent"

    async def test_system_prompt_property(self, agent):
        assert "test agent" in agent.system_prompt

    async def test_call_llm_structured(self, mock_llm):
        from pydantic import BaseModel

        class Output(BaseModel):
            score: int = 5

        mock_llm.complete_structured.return_value = (
            LLMResponse(
                content="{}",
                model="claude-sonnet-4-6",
                input_tokens=50,
                output_tokens=25,
                cost_usd=0.0005,
                stop_reason="end_turn",
            ),
            Output(score=5),
        )
        agent = ConcreteAgent(llm=mock_llm)
        response, parsed = await agent.call_llm_structured(
            [{"role": "user", "content": "rate"}],
            output_schema=Output,
        )
        assert parsed.score == 5
```

## Verify

```bash
uv run pytest tests/unit/test_llm_client.py tests/unit/test_agent_base.py -v
uv run ruff check src/omnicast/llm/ src/omnicast/agents/base.py
uv run pyright src/omnicast/llm/ src/omnicast/agents/base.py
```
